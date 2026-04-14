from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_gerente, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/veiculos", tags=["veículos"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VehicleCreate(BaseModel):
    plate: str
    model: str
    brand: str | None = None
    year: int | None = None
    color: str | None = None
    document_url: str | None = None


class VehicleUpdate(BaseModel):
    model: str | None = None
    brand: str | None = None
    year: int | None = None
    color: str | None = None
    document_url: str | None = None
    is_active: bool | None = None


class VehicleResponse(BaseModel):
    id: str
    plate: str
    model: str
    brand: str | None
    year: int | None
    color: str | None
    document_url: str | None
    is_active: bool
    created_at: str
    updated_at: str


class MaintenanceCreate(BaseModel):
    type: str
    scheduled_at: str | None = None
    scheduled_km: int | None = None
    notes: str | None = None


class MaintenanceUpdate(BaseModel):
    type: str | None = None
    status: str | None = None   # agendada, realizada, cancelada
    scheduled_at: str | None = None
    scheduled_km: int | None = None
    done_at: str | None = None
    done_km: int | None = None
    cost: float | None = None
    notes: str | None = None
    receipt_url: str | None = None


class MaintenanceResponse(BaseModel):
    id: str
    vehicle_id: str
    vehicle_plate: str
    type: str
    status: str
    scheduled_at: str | None
    scheduled_km: int | None
    done_at: str | None
    done_km: int | None
    cost: float | None
    notes: str | None
    receipt_url: str | None
    created_at: str


class FineCreate(BaseModel):
    amount: float
    infraction_date: str | None = None
    description: str | None = None
    service_order_id: str | None = None


class FineUpdate(BaseModel):
    paid: bool | None = None
    paid_at: str | None = None
    receipt_url: str | None = None
    description: str | None = None


class FineResponse(BaseModel):
    id: str
    vehicle_id: str
    vehicle_plate: str
    service_order_id: str | None
    os_number: str | None
    amount: float
    infraction_date: str | None
    description: str | None
    paid: bool
    paid_at: str | None
    receipt_url: str | None
    created_at: str


class RefuelingCreate(BaseModel):
    liters: float | None = None
    price_per_liter: float | None = None
    total_cost: float
    km_at_refuel: int | None = None
    refuel_date: str
    service_order_id: str | None = None
    receipt_url: str | None = None


class RefuelingResponse(BaseModel):
    id: str
    vehicle_id: str
    vehicle_plate: str
    service_order_id: str | None
    os_number: str | None
    liters: float | None
    price_per_liter: float | None
    total_cost: float
    km_at_refuel: int | None
    refuel_date: str
    receipt_url: str | None
    created_at: str


class KmLogResponse(BaseModel):
    id: str
    vehicle_id: str
    service_order_id: str | None
    os_number: str | None
    km_outbound: int
    km_return: int
    km_total: int
    log_date: str
    created_at: str


class VehicleCostSummary(BaseModel):
    vehicle_id: str
    plate: str
    model: str
    maintenance_cost: float
    fuel_cost: float
    fines_cost: float
    total_cost: float
    total_km: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_vehicle(row) -> VehicleResponse:
    m = dict(row._mapping)
    return VehicleResponse(
        id=str(m["id"]),
        plate=m["plate"],
        model=m["model"],
        brand=m.get("brand"),
        year=m.get("year"),
        color=m.get("color"),
        document_url=m.get("document_url"),
        is_active=m["is_active"],
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
    )


def row_to_maintenance(row) -> MaintenanceResponse:
    m = dict(row._mapping)
    return MaintenanceResponse(
        id=str(m["id"]),
        vehicle_id=str(m["vehicle_id"]),
        vehicle_plate=m.get("vehicle_plate", ""),
        type=m["type"],
        status=m["status"],
        scheduled_at=str(m["scheduled_at"]) if m.get("scheduled_at") else None,
        scheduled_km=m.get("scheduled_km"),
        done_at=str(m["done_at"]) if m.get("done_at") else None,
        done_km=m.get("done_km"),
        cost=float(m["cost"]) if m.get("cost") else None,
        notes=m.get("notes"),
        receipt_url=m.get("receipt_url"),
        created_at=str(m["created_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Veículos
# ---------------------------------------------------------------------------

@router.get("", response_model=Page[VehicleResponse], summary="Listar veículos")
async def listar_veiculos(
    search: str | None = Query(None, description="Busca por placa ou modelo"),
    is_active: bool | None = Query(None),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if search:
        conditions.append(
            "(lower(plate) ilike lower(:search) OR lower(model) ilike lower(:search))"
        )
        params["search"] = f"%{search}%"

    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM vehicles WHERE {where}"), params
    )
    total = count.scalar()
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"""
            SELECT id::text, plate, model, brand, year, color,
                   document_url, is_active, created_at::text, updated_at::text
            FROM vehicles
            WHERE {where}
            ORDER BY plate
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [row_to_vehicle(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("", response_model=VehicleResponse, status_code=201, summary="Cadastrar veículo")
async def criar_veiculo(
    body: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    # Verificar placa duplicada
    check = await db.execute(
        text("SELECT id FROM vehicles WHERE lower(plate) = lower(:plate)"),
        {"plate": body.plate},
    )
    if check.fetchone():
        raise HTTPException(status_code=409, detail=f"Veículo com placa {body.plate} já cadastrado")

    result = await db.execute(
        text("""
            INSERT INTO vehicles (plate, model, brand, year, color, document_url)
            VALUES (:plate, :model, :brand, :year, :color, :document_url)
            RETURNING id::text, plate, model, brand, year, color,
                      document_url, is_active, created_at::text, updated_at::text
        """),
        body.model_dump(),
    )
    return row_to_vehicle(result.fetchone())


@router.get("/{vehicle_id}", response_model=VehicleResponse, summary="Buscar veículo")
async def buscar_veiculo(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT id::text, plate, model, brand, year, color,
                   document_url, is_active, created_at::text, updated_at::text
            FROM vehicles WHERE id = :id
        """),
        {"id": str(vehicle_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return row_to_vehicle(row)


@router.patch("/{vehicle_id}", response_model=VehicleResponse, summary="Atualizar veículo")
async def atualizar_veiculo(
    vehicle_id: UUID,
    body: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(vehicle_id)

    result = await db.execute(
        text(f"""
            UPDATE vehicles SET {set_clause}, updated_at = now()
            WHERE id = :id
            RETURNING id::text, plate, model, brand, year, color,
                      document_url, is_active, created_at::text, updated_at::text
        """),
        updates,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return row_to_vehicle(row)


# ---------------------------------------------------------------------------
# Endpoints — Manutenções
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/manutencoes", response_model=list[MaintenanceResponse], summary="Listar manutenções")
async def listar_manutencoes(
    vehicle_id: UUID,
    status: str | None = Query(None, description="agendada, realizada, cancelada"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["vm.vehicle_id = :vehicle_id"]
    params: dict[str, Any] = {"vehicle_id": str(vehicle_id)}

    if status:
        conditions.append("vm.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT
                vm.id::text, vm.vehicle_id::text, v.plate as vehicle_plate,
                vm.type, vm.status, vm.scheduled_at::text, vm.scheduled_km,
                vm.done_at::text, vm.done_km, vm.cost, vm.notes,
                vm.receipt_url, vm.created_at::text
            FROM vehicle_maintenances vm
            JOIN vehicles v ON v.id = vm.vehicle_id
            WHERE {where}
            ORDER BY vm.scheduled_at DESC
        """),
        params,
    )
    return [row_to_maintenance(r) for r in result.fetchall()]


@router.get("/manutencoes/alertas", summary="Alertas de manutenção próxima")
async def alertas_manutencao(
    days_ahead: int = Query(default=30, description="Dias à frente para verificar"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """Lista veículos com manutenção agendada nos próximos N dias."""
    result = await db.execute(
        text("""
            SELECT
                vm.id::text,
                v.plate, v.model,
                vm.type,
                vm.scheduled_at::text,
                vm.scheduled_km,
                (vm.scheduled_at - current_date) as days_remaining
            FROM vehicle_maintenances vm
            JOIN vehicles v ON v.id = vm.vehicle_id
            WHERE vm.status = 'agendada'
            AND vm.scheduled_at IS NOT NULL
            AND vm.scheduled_at <= current_date + :days_ahead
            ORDER BY vm.scheduled_at
        """),
        {"days_ahead": days_ahead},
    )
    return [dict(r._mapping) for r in result.fetchall()]


@router.post("/{vehicle_id}/manutencoes", response_model=MaintenanceResponse, status_code=201, summary="Agendar manutenção")
async def agendar_manutencao(
    vehicle_id: UUID,
    body: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO vehicle_maintenances
                (vehicle_id, type, scheduled_at, scheduled_km, notes)
            VALUES
                (:vehicle_id, :type, :scheduled_at, :scheduled_km, :notes)
            RETURNING id::text, vehicle_id::text, type, status,
                      scheduled_at::text, scheduled_km, done_at::text, done_km,
                      cost, notes, receipt_url, created_at::text
        """),
        {"vehicle_id": str(vehicle_id), **body.model_dump()},
    )
    row = result.fetchone()
    m = dict(row._mapping)

    plate_result = await db.execute(
        text("SELECT plate FROM vehicles WHERE id = :id"), {"id": str(vehicle_id)}
    )
    plate_row = plate_result.fetchone()
    m["vehicle_plate"] = plate_row.plate if plate_row else ""
    return row_to_maintenance(type("Row", (), {"_mapping": m})())


@router.patch("/{vehicle_id}/manutencoes/{maintenance_id}", response_model=MaintenanceResponse, summary="Atualizar manutenção")
async def atualizar_manutencao(
    vehicle_id: UUID,
    maintenance_id: UUID,
    body: MaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(maintenance_id)
    updates["vehicle_id"] = str(vehicle_id)

    result = await db.execute(
        text(f"""
            UPDATE vehicle_maintenances SET {set_clause}
            WHERE id = :id AND vehicle_id = :vehicle_id
            RETURNING id::text, vehicle_id::text, type, status,
                      scheduled_at::text, scheduled_km, done_at::text, done_km,
                      cost, notes, receipt_url, created_at::text
        """),
        updates,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Manutenção não encontrada")

    m = dict(row._mapping)
    plate_result = await db.execute(
        text("SELECT plate FROM vehicles WHERE id = :id"), {"id": str(vehicle_id)}
    )
    plate_row = plate_result.fetchone()
    m["vehicle_plate"] = plate_row.plate if plate_row else ""
    return row_to_maintenance(type("Row", (), {"_mapping": m})())


# ---------------------------------------------------------------------------
# Endpoints — Multas
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/multas", response_model=list[FineResponse], summary="Listar multas")
async def listar_multas(
    vehicle_id: UUID,
    paid: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["vf.vehicle_id = :vehicle_id"]
    params: dict[str, Any] = {"vehicle_id": str(vehicle_id)}

    if paid is not None:
        conditions.append("vf.paid = :paid")
        params["paid"] = paid

    result = await db.execute(
        text(f"""
            SELECT
                vf.id::text, vf.vehicle_id::text, v.plate as vehicle_plate,
                vf.service_order_id::text, so.os_number,
                vf.amount, vf.infraction_date::text,
                vf.description, vf.paid, vf.paid_at::text,
                vf.receipt_url, vf.created_at::text
            FROM vehicle_fines vf
            JOIN vehicles v ON v.id = vf.vehicle_id
            LEFT JOIN service_orders so ON so.id = vf.service_order_id
            WHERE {" AND ".join(conditions)}
            ORDER BY vf.infraction_date DESC
        """),
        params,
    )
    rows = result.fetchall()
    return [
        FineResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "vehicle_id": str(dict(r._mapping)["vehicle_id"]),
            "service_order_id": str(dict(r._mapping)["service_order_id"]) if dict(r._mapping).get("service_order_id") else None,
            "amount": float(dict(r._mapping)["amount"]),
            "infraction_date": str(dict(r._mapping)["infraction_date"]) if dict(r._mapping).get("infraction_date") else None,
            "paid_at": str(dict(r._mapping)["paid_at"]) if dict(r._mapping).get("paid_at") else None,
            "created_at": str(dict(r._mapping)["created_at"]),
        })
        for r in rows
    ]


@router.post("/{vehicle_id}/multas", response_model=FineResponse, status_code=201, summary="Registrar multa")
async def registrar_multa(
    vehicle_id: UUID,
    body: FineCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO vehicle_fines
                (vehicle_id, amount, infraction_date, description, service_order_id)
            VALUES
                (:vehicle_id, :amount, :infraction_date, :description, :service_order_id)
            RETURNING id::text, vehicle_id::text, service_order_id::text,
                      amount, infraction_date::text, description,
                      paid, paid_at::text, receipt_url, created_at::text
        """),
        {"vehicle_id": str(vehicle_id), **body.model_dump()},
    )
    m = dict(result.fetchone()._mapping)

    plate_result = await db.execute(
        text("SELECT plate FROM vehicles WHERE id = :id"), {"id": str(vehicle_id)}
    )
    plate_row = plate_result.fetchone()

    os_number = None
    if m.get("service_order_id"):
        os_result = await db.execute(
            text("SELECT os_number FROM service_orders WHERE id = :id"),
            {"id": m["service_order_id"]},
        )
        os_row = os_result.fetchone()
        os_number = os_row.os_number if os_row else None

    return FineResponse(
        id=str(m["id"]),
        vehicle_id=str(m["vehicle_id"]),
        vehicle_plate=plate_row.plate if plate_row else "",
        service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
        os_number=os_number,
        amount=float(m["amount"]),
        infraction_date=str(m["infraction_date"]) if m.get("infraction_date") else None,
        description=m.get("description"),
        paid=m["paid"],
        paid_at=str(m["paid_at"]) if m.get("paid_at") else None,
        receipt_url=m.get("receipt_url"),
        created_at=str(m["created_at"]),
    )


@router.patch("/{vehicle_id}/multas/{fine_id}", response_model=FineResponse, summary="Atualizar multa (pagamento)")
async def atualizar_multa(
    vehicle_id: UUID,
    fine_id: UUID,
    body: FineUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(fine_id)
    updates["vehicle_id"] = str(vehicle_id)

    result = await db.execute(
        text(f"""
            UPDATE vehicle_fines SET {set_clause}
            WHERE id = :id AND vehicle_id = :vehicle_id
            RETURNING id::text, vehicle_id::text, service_order_id::text,
                      amount, infraction_date::text, description,
                      paid, paid_at::text, receipt_url, created_at::text
        """),
        updates,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Multa não encontrada")

    m = dict(row._mapping)
    plate_result = await db.execute(
        text("SELECT plate FROM vehicles WHERE id = :id"), {"id": str(vehicle_id)}
    )
    plate_row = plate_result.fetchone()

    return FineResponse(
        id=str(m["id"]),
        vehicle_id=str(m["vehicle_id"]),
        vehicle_plate=plate_row.plate if plate_row else "",
        service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
        os_number=None,
        amount=float(m["amount"]),
        infraction_date=str(m["infraction_date"]) if m.get("infraction_date") else None,
        description=m.get("description"),
        paid=m["paid"],
        paid_at=str(m["paid_at"]) if m.get("paid_at") else None,
        receipt_url=m.get("receipt_url"),
        created_at=str(m["created_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Abastecimentos
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/abastecimentos", response_model=list[RefuelingResponse], summary="Listar abastecimentos")
async def listar_abastecimentos(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                vr.id::text, vr.vehicle_id::text, v.plate as vehicle_plate,
                vr.service_order_id::text, so.os_number,
                vr.liters, vr.price_per_liter, vr.total_cost,
                vr.km_at_refuel, vr.refuel_date::text,
                vr.receipt_url, vr.created_at::text
            FROM vehicle_refueling vr
            JOIN vehicles v ON v.id = vr.vehicle_id
            LEFT JOIN service_orders so ON so.id = vr.service_order_id
            WHERE vr.vehicle_id = :vehicle_id
            ORDER BY vr.refuel_date DESC
        """),
        {"vehicle_id": str(vehicle_id)},
    )
    rows = result.fetchall()
    return [
        RefuelingResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "vehicle_id": str(dict(r._mapping)["vehicle_id"]),
            "service_order_id": str(dict(r._mapping)["service_order_id"]) if dict(r._mapping).get("service_order_id") else None,
            "total_cost": float(dict(r._mapping)["total_cost"]),
            "liters": float(dict(r._mapping)["liters"]) if dict(r._mapping).get("liters") else None,
            "price_per_liter": float(dict(r._mapping)["price_per_liter"]) if dict(r._mapping).get("price_per_liter") else None,
            "refuel_date": str(dict(r._mapping)["refuel_date"]),
            "created_at": str(dict(r._mapping)["created_at"]),
        })
        for r in rows
    ]


@router.post("/{vehicle_id}/abastecimentos", response_model=RefuelingResponse, status_code=201, summary="Registrar abastecimento")
async def registrar_abastecimento(
    vehicle_id: UUID,
    body: RefuelingCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO vehicle_refueling
                (vehicle_id, liters, price_per_liter, total_cost,
                 km_at_refuel, refuel_date, service_order_id, receipt_url)
            VALUES
                (:vehicle_id, :liters, :price_per_liter, :total_cost,
                 :km_at_refuel, :refuel_date, :service_order_id, :receipt_url)
            RETURNING id::text, vehicle_id::text, service_order_id::text,
                      liters, price_per_liter, total_cost, km_at_refuel,
                      refuel_date::text, receipt_url, created_at::text
        """),
        {"vehicle_id": str(vehicle_id), **body.model_dump()},
    )
    m = dict(result.fetchone()._mapping)

    plate_result = await db.execute(
        text("SELECT plate FROM vehicles WHERE id = :id"), {"id": str(vehicle_id)}
    )
    plate_row = plate_result.fetchone()

    os_number = None
    if m.get("service_order_id"):
        os_result = await db.execute(
            text("SELECT os_number FROM service_orders WHERE id = :id"),
            {"id": m["service_order_id"]},
        )
        os_row = os_result.fetchone()
        os_number = os_row.os_number if os_row else None

    return RefuelingResponse(
        id=str(m["id"]),
        vehicle_id=str(m["vehicle_id"]),
        vehicle_plate=plate_row.plate if plate_row else "",
        service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
        os_number=os_number,
        liters=float(m["liters"]) if m.get("liters") else None,
        price_per_liter=float(m["price_per_liter"]) if m.get("price_per_liter") else None,
        total_cost=float(m["total_cost"]),
        km_at_refuel=m.get("km_at_refuel"),
        refuel_date=str(m["refuel_date"]),
        receipt_url=m.get("receipt_url"),
        created_at=str(m["created_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Km logs
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/km", response_model=list[KmLogResponse], summary="Histórico de km")
async def historico_km(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                kl.id::text, kl.vehicle_id::text,
                kl.service_order_id::text, so.os_number,
                kl.km_outbound, kl.km_return, kl.km_total,
                kl.log_date::text, kl.created_at::text
            FROM vehicle_km_logs kl
            LEFT JOIN service_orders so ON so.id = kl.service_order_id
            WHERE kl.vehicle_id = :vehicle_id
            ORDER BY kl.log_date DESC
        """),
        {"vehicle_id": str(vehicle_id)},
    )
    return [
        KmLogResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "vehicle_id": str(dict(r._mapping)["vehicle_id"]),
            "service_order_id": str(dict(r._mapping)["service_order_id"]) if dict(r._mapping).get("service_order_id") else None,
            "log_date": str(dict(r._mapping)["log_date"]),
            "created_at": str(dict(r._mapping)["created_at"]),
        })
        for r in result.fetchall()
    ]


# ---------------------------------------------------------------------------
# Endpoints — Relatórios e custos
# ---------------------------------------------------------------------------

@router.get("/custos/resumo", response_model=list[VehicleCostSummary], summary="Custo total por veículo")
async def custos_resumo(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Retorna o custo consolidado de cada veículo usando a view vehicle_cost_summary.
    Inclui manutenções realizadas, combustível, multas e km total.
    """
    result = await db.execute(
        text("""
            SELECT vehicle_id::text, plate, model,
                   maintenance_cost, fuel_cost, fines_cost,
                   total_cost, total_km
            FROM vehicle_cost_summary
            ORDER BY total_cost DESC
        """)
    )
    return [
        VehicleCostSummary(**{
            **dict(r._mapping),
            "maintenance_cost": float(dict(r._mapping)["maintenance_cost"]),
            "fuel_cost": float(dict(r._mapping)["fuel_cost"]),
            "fines_cost": float(dict(r._mapping)["fines_cost"]),
            "total_cost": float(dict(r._mapping)["total_cost"]),
            "total_km": int(dict(r._mapping)["total_km"]),
        })
        for r in result.fetchall()
    ]


@router.get("/{vehicle_id}/custos", summary="Custos detalhados do veículo")
async def custos_veiculo(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Custo detalhado por categoria para um veículo específico."""
    result = await db.execute(
        text("""
            SELECT vehicle_id::text, plate, model,
                   maintenance_cost, fuel_cost, fines_cost,
                   total_cost, total_km
            FROM vehicle_cost_summary
            WHERE vehicle_id = :id
        """),
        {"id": str(vehicle_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    m = dict(row._mapping)

    # Consumo médio
    consumo_medio = None
    if m.get("total_km") and m.get("fuel_cost") and float(m["fuel_cost"]) > 0:
        fuel_liters_result = await db.execute(
            text("SELECT coalesce(sum(liters), 0) FROM vehicle_refueling WHERE vehicle_id = :id AND liters IS NOT NULL"),
            {"id": str(vehicle_id)},
        )
        total_liters = float(fuel_liters_result.scalar() or 0)
        if total_liters > 0:
            consumo_medio = round(int(m["total_km"]) / total_liters, 2)

    return {
        "vehicle_id": str(m["vehicle_id"]),
        "plate": m["plate"],
        "model": m["model"],
        "custos": {
            "manutencao": float(m["maintenance_cost"]),
            "combustivel": float(m["fuel_cost"]),
            "multas": float(m["fines_cost"]),
            "total": float(m["total_cost"]),
        },
        "km_total": int(m["total_km"]),
        "consumo_medio_km_por_litro": consumo_medio,
    }
