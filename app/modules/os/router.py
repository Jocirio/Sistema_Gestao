from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_user, require_gerente, require_financeiro, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/os", tags=["ordens de serviço"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OSCreate(BaseModel):
    collaborator_id: str
    client_id: str
    client_unit_id: str | None = None
    sector_id: str | None = None
    transport_type: str = "outro"
    vehicle_id: str | None = None
    km_outbound: int | None = None
    departure_date: str   # ISO date
    return_date: str      # ISO date
    services_description: str | None = None

    @field_validator("transport_type")
    @classmethod
    def valid_transport(cls, v: str) -> str:
        allowed = {"frota_propria", "veiculo_proprio", "transporte_publico", "aereo", "outro"}
        if v not in allowed:
            raise ValueError(f"transport_type deve ser um de: {', '.join(allowed)}")
        return v


class OSUpdate(BaseModel):
    client_unit_id: str | None = None
    sector_id: str | None = None
    transport_type: str | None = None
    vehicle_id: str | None = None
    km_outbound: int | None = None
    departure_date: str | None = None
    return_date: str | None = None
    services_description: str | None = None


class AdvanceCreate(BaseModel):
    advance_type_id: str
    amount: float
    notes: str | None = None


class AdvanceResponse(BaseModel):
    id: str
    service_order_id: str
    advance_type_id: str
    advance_type_name: str
    amount: float
    notes: str | None
    created_by: str | None
    created_at: str


class ExtraCostCreate(BaseModel):
    description: str
    amount: float
    receipt_url: str | None = None


class ExtraCostResponse(BaseModel):
    id: str
    service_order_id: str
    description: str
    amount: float
    receipt_url: str | None
    created_by: str
    created_at: str


class AccountItemCreate(BaseModel):
    advance_type_id: str | None = None
    description: str
    amount: float
    receipt_url: str | None = None


class AccountItemResponse(BaseModel):
    id: str
    service_order_id: str
    advance_type_id: str | None
    description: str
    amount: float
    receipt_url: str | None
    created_at: str


class SettlementSubmit(BaseModel):
    """Colaborador envia a prestação de contas."""
    items: list[AccountItemCreate]


class SettlementReview(BaseModel):
    """Financeiro aceita ou recusa a prestação de contas."""
    approved: bool
    notes: str | None = None


class SettlementClose(BaseModel):
    """Financeiro registra a devolução física do saldo."""
    settlement_proof_url: str | None = None
    settlement_notes: str | None = None


class StatusChange(BaseModel):
    notes: str | None = None


class OSResponse(BaseModel):
    id: str
    os_number: str
    issued_at: str
    status: str
    # Setor
    sector_id: str | None
    sector_name: str | None
    # Colaborador
    collaborator_id: str
    collaborator_name: str
    collaborator_function: str | None
    # Cliente
    client_id: str
    client_name: str
    client_unit_id: str | None
    client_unit_name: str | None
    # Transporte
    transport_type: str
    vehicle_id: str | None
    vehicle_plate: str | None
    km_outbound: int | None
    km_return: int | None
    km_total: int | None
    # Datas
    departure_date: str
    return_date: str
    days_away: int | None
    # Serviços
    services_description: str | None
    # Financeiro
    daily_rate_snapshot: float | None
    daily_total: float | None
    advances_total: float
    extra_costs_total: float
    spent_total: float | None
    balance: float | None
    # Acerto
    settlement_status: str | None
    settled_at: str | None
    settlement_notes: str | None
    # Emissor
    issued_by: str
    issued_by_name: str
    # Rejeição
    rejection_reason: str | None
    # Datas
    created_at: str
    updated_at: str


class OSAuditEntry(BaseModel):
    id: str
    from_status: str | None
    to_status: str
    changed_by: str
    changed_by_name: str
    notes: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OS_SELECT = """
    SELECT
        so.id::text,
        so.os_number,
        so.issued_at::text,
        so.status,
        so.sector_id::text,
        sec.name                    as sector_name,
        so.collaborator_id::text,
        pc.full_name                as collaborator_name,
        jf.name                     as collaborator_function,
        so.client_id::text,
        cl.name                     as client_name,
        so.client_unit_id::text,
        cu.name                     as client_unit_name,
        so.transport_type,
        so.vehicle_id::text,
        v.plate                     as vehicle_plate,
        so.km_outbound,
        so.km_return,
        so.km_total,
        so.departure_date::text,
        so.return_date::text,
        so.days_away,
        so.services_description,
        so.daily_rate_snapshot,
        so.daily_total,
        so.advances_total,
        so.extra_costs_total,
        so.spent_total,
        so.balance,
        so.settlement_status,
        so.settled_at::text,
        so.settlement_notes,
        so.issued_by::text,
        pi2.full_name               as issued_by_name,
        so.rejection_reason,
        so.created_at::text,
        so.updated_at::text
    FROM service_orders so
    LEFT JOIN os_sectors sec   ON sec.id  = so.sector_id
    LEFT JOIN profiles pc      ON pc.id   = so.collaborator_id
    LEFT JOIN job_functions jf ON jf.id   = pc.job_function_id
    LEFT JOIN clients cl       ON cl.id   = so.client_id
    LEFT JOIN client_units cu  ON cu.id   = so.client_unit_id
    LEFT JOIN vehicles v       ON v.id    = so.vehicle_id
    LEFT JOIN profiles pi2     ON pi2.id  = so.issued_by
"""


def row_to_os(row) -> OSResponse:
    m = dict(row._mapping)
    return OSResponse(
        id=m["id"],
        os_number=m["os_number"],
        issued_at=m["issued_at"],
        status=m["status"],
        sector_id=m.get("sector_id"),
        sector_name=m.get("sector_name"),
        collaborator_id=m["collaborator_id"],
        collaborator_name=m.get("collaborator_name", ""),
        collaborator_function=m.get("collaborator_function"),
        client_id=m["client_id"],
        client_name=m.get("client_name", ""),
        client_unit_id=m.get("client_unit_id"),
        client_unit_name=m.get("client_unit_name"),
        transport_type=m["transport_type"],
        vehicle_id=m.get("vehicle_id"),
        vehicle_plate=m.get("vehicle_plate"),
        km_outbound=m.get("km_outbound"),
        km_return=m.get("km_return"),
        km_total=m.get("km_total"),
        departure_date=m["departure_date"],
        return_date=m["return_date"],
        days_away=m.get("days_away"),
        services_description=m.get("services_description"),
        daily_rate_snapshot=float(m["daily_rate_snapshot"]) if m.get("daily_rate_snapshot") else None,
        daily_total=float(m["daily_total"]) if m.get("daily_total") else None,
        advances_total=float(m.get("advances_total", 0)),
        extra_costs_total=float(m.get("extra_costs_total", 0)),
        spent_total=float(m["spent_total"]) if m.get("spent_total") else None,
        balance=float(m["balance"]) if m.get("balance") else None,
        settlement_status=m.get("settlement_status"),
        settled_at=m.get("settled_at"),
        settlement_notes=m.get("settlement_notes"),
        issued_by=m["issued_by"],
        issued_by_name=m.get("issued_by_name", ""),
        rejection_reason=m.get("rejection_reason"),
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


async def get_os_or_404(db: AsyncSession, os_id: str) -> OSResponse:
    result = await db.execute(
        text(f"{OS_SELECT} WHERE so.id = :id"),
        {"id": os_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="O.S. não encontrada")
    return row_to_os(row)


async def check_collaborator_blocked(db: AsyncSession, collaborator_id: str) -> None:
    result = await db.execute(
        text("SELECT os_blocked, blocked_reason FROM profiles WHERE id = :id"),
        {"id": collaborator_id},
    )
    row = result.fetchone()
    if row and row.os_blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Colaborador bloqueado: {row.blocked_reason or 'adiantamento pendente de devolução'}",
        )


async def calculate_daily_total(db: AsyncSession, collaborator_id: str, days_away: int) -> tuple[float, float]:
    """Retorna (daily_rate, daily_total) com base na função do colaborador."""
    result = await db.execute(
        text("""
            SELECT jf.daily_rate
            FROM profiles p
            LEFT JOIN job_functions jf ON jf.id = p.job_function_id
            WHERE p.id = :id
        """),
        {"id": collaborator_id},
    )
    row = result.fetchone()
    daily_rate = float(row.daily_rate) if row and row.daily_rate else 0.0
    daily_total = round(daily_rate * days_away, 2)
    return daily_rate, daily_total


# ---------------------------------------------------------------------------
# Endpoints — CRUD principal
# ---------------------------------------------------------------------------

@router.get("", response_model=Page[OSResponse], summary="Listar O.S.")
async def listar_os(
    status_filter: str | None = Query(None, alias="status", description="Filtrar por status"),
    collaborator_id: str | None = Query(None),
    client_id: str | None = Query(None),
    sector_id: str | None = Query(None),
    departure_from: str | None = Query(None, description="Data de ida a partir de (YYYY-MM-DD)"),
    departure_to: str | None = Query(None, description="Data de ida até (YYYY-MM-DD)"),
    settlement: str | None = Query(None, description="Filtrar por settlement_status"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Lista O.S. com filtros. Colaboradores veem apenas as próprias.
    Gerente, financeiro, comercial e admin veem todas.
    """
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    # Colaborador só vê as próprias
    if current_user.role == "colaborador":
        conditions.append("so.collaborator_id = :current_uid")
        params["current_uid"] = str(current_user.user_id)
    elif collaborator_id:
        conditions.append("so.collaborator_id = :collaborator_id")
        params["collaborator_id"] = collaborator_id

    if status_filter:
        conditions.append("so.status = :status")
        params["status"] = status_filter

    if client_id:
        conditions.append("so.client_id = :client_id")
        params["client_id"] = client_id

    if sector_id:
        conditions.append("so.sector_id = :sector_id")
        params["sector_id"] = sector_id

    if departure_from:
        conditions.append("so.departure_date >= :departure_from")
        params["departure_from"] = departure_from

    if departure_to:
        conditions.append("so.departure_date <= :departure_to")
        params["departure_to"] = departure_to

    if settlement:
        conditions.append("so.settlement_status = :settlement")
        params["settlement"] = settlement

    where = " AND ".join(conditions)

    count_result = await db.execute(
        text(f"SELECT count(*) FROM service_orders so WHERE {where}"),
        params,
    )
    total = count_result.scalar()

    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{OS_SELECT} WHERE {where} ORDER BY so.created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_os(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("", response_model=OSResponse, status_code=201, summary="Criar O.S.")
async def criar_os(
    body: OSCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Cria uma nova Ordem de Serviço em status 'rascunho'.
    Comercial, Gerente e Financeiro podem emitir.
    Verifica se o colaborador está bloqueado por adiantamento pendente.
    """
    if current_user.role == "colaborador":
        raise HTTPException(status_code=403, detail="Colaboradores não podem emitir O.S.")

    # Verificar bloqueio do colaborador
    await check_collaborator_blocked(db, body.collaborator_id)

    # Calcular diárias
    dep = date.fromisoformat(body.departure_date)
    ret = date.fromisoformat(body.return_date)
    if ret < dep:
        raise HTTPException(status_code=400, detail="Data de volta deve ser igual ou posterior à de ida")
    days_away = (ret - dep).days + 1
    daily_rate, daily_total = await calculate_daily_total(db, body.collaborator_id, days_away)

    result = await db.execute(
        text("""
            INSERT INTO service_orders (
                collaborator_id, client_id, client_unit_id, sector_id,
                transport_type, vehicle_id, km_outbound,
                departure_date, return_date,
                services_description,
                daily_rate_snapshot, daily_total,
                issued_by
            ) VALUES (
                :collaborator_id, :client_id, :client_unit_id, :sector_id,
                :transport_type, :vehicle_id, :km_outbound,
                :departure_date, :return_date,
                :services_description,
                :daily_rate, :daily_total,
                :issued_by
            )
            RETURNING id::text
        """),
        {
            "collaborator_id": body.collaborator_id,
            "client_id": body.client_id,
            "client_unit_id": body.client_unit_id,
            "sector_id": body.sector_id,
            "transport_type": body.transport_type,
            "vehicle_id": body.vehicle_id,
            "km_outbound": body.km_outbound,
            "departure_date": body.departure_date,
            "return_date": body.return_date,
            "services_description": body.services_description,
            "daily_rate": daily_rate,
            "daily_total": daily_total,
            "issued_by": str(current_user.user_id),
        },
    )
    os_id = result.fetchone().id

    # Se transporte é frota própria e km foi informado, registrar no histórico do veículo
    if body.transport_type == "frota_propria" and body.vehicle_id and body.km_outbound:
        await db.execute(
            text("""
                INSERT INTO vehicle_km_logs (vehicle_id, service_order_id, km_outbound, km_return, log_date)
                VALUES (:vehicle_id, :os_id, :km_outbound, :km_return, :log_date)
            """),
            {
                "vehicle_id": body.vehicle_id,
                "os_id": os_id,
                "km_outbound": body.km_outbound,
                "km_return": body.km_outbound * 2,
                "log_date": body.departure_date,
            },
        )

    return await get_os_or_404(db, os_id)


@router.get("/pendentes-devolucao", summary="O.S. com adiantamento pendente de devolução")
async def os_pendentes_devolucao(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """
    Retorna todas as OS com saldo a devolver pelo colaborador.
    Usa a view os_pending_settlements do banco.
    """
    result = await db.execute(
        text("""
            SELECT
                id::text, os_number, collaborator_id::text, collaborator_name,
                settlement_status, balance, last_updated::text,
                days_open, max_days, max_os_allowed
            FROM os_pending_settlements
            ORDER BY days_open DESC
        """),
    )
    return [dict(r._mapping) for r in result.fetchall()]


@router.get("/{os_id}", response_model=OSResponse, summary="Buscar O.S. por ID")
async def buscar_os(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    os = await get_os_or_404(db, str(os_id))

    # Colaborador só pode ver a própria
    if current_user.role == "colaborador" and os.collaborator_id != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    return os


@router.patch("/{os_id}", response_model=OSResponse, summary="Atualizar O.S.")
async def atualizar_os(
    os_id: UUID,
    body: OSUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Atualiza campos da O.S. Só permitido em status 'rascunho' ou 'devolvida'.
    Colaborador pode editar apenas quando a OS foi devolvida para ele.
    """
    os = await get_os_or_404(db, str(os_id))

    if current_user.role == "colaborador":
        if os.collaborator_id != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Acesso não permitido")
        if os.status != "devolvida":
            raise HTTPException(status_code=409, detail="Colaborador só pode editar O.S. devolvida")
    else:
        if os.status not in ("rascunho", "devolvida"):
            raise HTTPException(status_code=409, detail="O.S. só pode ser editada em rascunho ou devolvida")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Recalcular diárias se datas mudaram
    if "departure_date" in updates or "return_date" in updates:
        dep_str = updates.get("departure_date", os.departure_date)
        ret_str = updates.get("return_date", os.return_date)
        dep = date.fromisoformat(dep_str)
        ret = date.fromisoformat(ret_str)
        if ret < dep:
            raise HTTPException(status_code=400, detail="Data de volta deve ser igual ou posterior à de ida")
        days_away = (ret - dep).days + 1
        daily_rate, daily_total = await calculate_daily_total(db, os.collaborator_id, days_away)
        updates["daily_rate_snapshot"] = daily_rate
        updates["daily_total"] = daily_total

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(os_id)

    await db.execute(
        text(f"UPDATE service_orders SET {set_clause}, updated_at = now() WHERE id = :id"),
        updates,
    )
    return await get_os_or_404(db, str(os_id))


# ---------------------------------------------------------------------------
# Endpoints — Mudanças de status
# ---------------------------------------------------------------------------

@router.post("/{os_id}/emitir", response_model=OSResponse, summary="Emitir O.S.")
async def emitir_os(
    os_id: UUID,
    body: StatusChange = StatusChange(),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Muda status de 'rascunho' para 'emitida'.
    A O.S. fica visível para o colaborador com confirmação de recebimento.
    """
    if current_user.role == "colaborador":
        raise HTTPException(status_code=403, detail="Colaboradores não podem emitir O.S.")

    os = await get_os_or_404(db, str(os_id))
    if os.status != "rascunho":
        raise HTTPException(status_code=409, detail=f"O.S. está em '{os.status}' — só rascunho pode ser emitida")

    await db.execute(
        text("UPDATE service_orders SET status = 'emitida', updated_at = now() WHERE id = :id"),
        {"id": str(os_id)},
    )
    return await get_os_or_404(db, str(os_id))


@router.post("/{os_id}/confirmar-recebimento", response_model=OSResponse, summary="Colaborador confirma recebimento")
async def confirmar_recebimento(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Colaborador confirma que recebeu e leu a O.S.
    Muda status de 'emitida' para 'em_execucao'.
    """
    os = await get_os_or_404(db, str(os_id))

    if os.collaborator_id != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Apenas o colaborador da O.S. pode confirmar o recebimento")

    if os.status != "emitida":
        raise HTTPException(status_code=409, detail=f"O.S. está em '{os.status}' — só emitida pode ser confirmada")

    await db.execute(
        text("UPDATE service_orders SET status = 'em_execucao', updated_at = now() WHERE id = :id"),
        {"id": str(os_id)},
    )
    return await get_os_or_404(db, str(os_id))


@router.post("/{os_id}/devolver", response_model=OSResponse, summary="Financeiro devolve O.S. ao colaborador")
async def devolver_os(
    os_id: UUID,
    body: StatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_financeiro),
):
    """Financeiro devolve a O.S. ao colaborador para ajuste, com justificativa obrigatória."""
    if not body.notes:
        raise HTTPException(status_code=400, detail="Justificativa obrigatória ao devolver")

    os = await get_os_or_404(db, str(os_id))
    if os.status not in ("aguardando_aceite",):
        raise HTTPException(status_code=409, detail="Só é possível devolver O.S. em 'aguardando_aceite'")

    await db.execute(
        text("""
            UPDATE service_orders
            SET status = 'devolvida',
                rejection_reason = :notes,
                updated_at = now()
            WHERE id = :id
        """),
        {"id": str(os_id), "notes": body.notes},
    )
    return await get_os_or_404(db, str(os_id))


@router.post("/{os_id}/reabrir", response_model=OSResponse, summary="Financeiro reabre O.S. encerrada")
async def reabrir_os(
    os_id: UUID,
    body: StatusChange,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """Financeiro pode reabrir uma O.S. encerrada para correção."""
    os = await get_os_or_404(db, str(os_id))
    if os.status != "encerrada":
        raise HTTPException(status_code=409, detail="Só O.S. encerrada pode ser reaberta")

    await db.execute(
        text("""
            UPDATE service_orders
            SET status = 'aguardando_aceite',
                settlement_status = 'em_aberto',
                settled_at = null,
                updated_at = now()
            WHERE id = :id
        """),
        {"id": str(os_id)},
    )
    return await get_os_or_404(db, str(os_id))


# ---------------------------------------------------------------------------
# Endpoints — Adiantamentos
# ---------------------------------------------------------------------------

@router.get("/{os_id}/adiantamentos", response_model=list[AdvanceResponse], summary="Listar adiantamentos")
async def listar_adiantamentos(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                a.id::text,
                a.service_order_id::text,
                a.advance_type_id::text,
                at2.name as advance_type_name,
                a.amount,
                a.notes,
                a.created_by::text,
                a.created_at::text
            FROM os_advances a
            JOIN advance_types at2 ON at2.id = a.advance_type_id
            WHERE a.service_order_id = :os_id
            ORDER BY a.created_at
        """),
        {"os_id": str(os_id)},
    )
    return [AdvanceResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/{os_id}/adiantamentos", response_model=AdvanceResponse, status_code=201, summary="Adicionar adiantamento")
async def adicionar_adiantamento(
    os_id: UUID,
    body: AdvanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Adiciona um adiantamento à O.S. Apenas em rascunho ou emitida."""
    if current_user.role == "colaborador":
        raise HTTPException(status_code=403, detail="Colaboradores não podem adicionar adiantamentos")

    os = await get_os_or_404(db, str(os_id))
    if os.status not in ("rascunho", "emitida"):
        raise HTTPException(status_code=409, detail="Adiantamentos só podem ser adicionados em rascunho ou emitida")

    # Verificar limite do tipo de adiantamento
    limit_result = await db.execute(
        text("SELECT max_value FROM advance_types WHERE id = :id"),
        {"id": body.advance_type_id},
    )
    limit_row = limit_result.fetchone()
    if limit_row and limit_row.max_value and body.amount > float(limit_row.max_value):
        raise HTTPException(
            status_code=400,
            detail=f"Valor excede o limite para este tipo de adiantamento (máx: R$ {limit_row.max_value})",
        )

    result = await db.execute(
        text("""
            INSERT INTO os_advances (service_order_id, advance_type_id, amount, notes, created_by)
            VALUES (:os_id, :advance_type_id, :amount, :notes, :created_by)
            RETURNING
                id::text, service_order_id::text, advance_type_id::text,
                amount, notes, created_by::text, created_at::text
        """),
        {
            "os_id": str(os_id),
            "advance_type_id": body.advance_type_id,
            "amount": body.amount,
            "notes": body.notes,
            "created_by": str(current_user.user_id),
        },
    )
    row = result.fetchone()
    m = dict(row._mapping)

    # Buscar nome do tipo
    type_result = await db.execute(
        text("SELECT name FROM advance_types WHERE id = :id"),
        {"id": body.advance_type_id},
    )
    type_row = type_result.fetchone()
    m["advance_type_name"] = type_row.name if type_row else ""
    return AdvanceResponse(**m)


@router.delete("/{os_id}/adiantamentos/{advance_id}", status_code=204, summary="Remover adiantamento")
async def remover_adiantamento(
    os_id: UUID,
    advance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.role == "colaborador":
        raise HTTPException(status_code=403, detail="Sem permissão")

    result = await db.execute(
        text("DELETE FROM os_advances WHERE id = :id AND service_order_id = :os_id RETURNING id"),
        {"id": str(advance_id), "os_id": str(os_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Adiantamento não encontrado")


# ---------------------------------------------------------------------------
# Endpoints — Custos extras (financeiro)
# ---------------------------------------------------------------------------

@router.get("/{os_id}/custos-extras", response_model=list[ExtraCostResponse], summary="Listar custos extras")
async def listar_custos_extras(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                id::text, service_order_id::text, description,
                amount, receipt_url, created_by::text, created_at::text
            FROM os_extra_costs
            WHERE service_order_id = :os_id
            ORDER BY created_at
        """),
        {"os_id": str(os_id)},
    )
    return [ExtraCostResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/{os_id}/custos-extras", response_model=ExtraCostResponse, status_code=201, summary="Adicionar custo extra")
async def adicionar_custo_extra(
    os_id: UUID,
    body: ExtraCostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_financeiro),
):
    """Financeiro lança custo pago pela empresa que não estava nos adiantamentos."""
    result = await db.execute(
        text("""
            INSERT INTO os_extra_costs (service_order_id, description, amount, receipt_url, created_by)
            VALUES (:os_id, :description, :amount, :receipt_url, :created_by)
            RETURNING
                id::text, service_order_id::text, description,
                amount, receipt_url, created_by::text, created_at::text
        """),
        {
            "os_id": str(os_id),
            "description": body.description,
            "amount": body.amount,
            "receipt_url": body.receipt_url,
            "created_by": str(current_user.user_id),
        },
    )
    return ExtraCostResponse(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Prestação de contas (colaborador → financeiro)
# ---------------------------------------------------------------------------

@router.post("/{os_id}/prestacao-de-contas", response_model=OSResponse, summary="Enviar prestação de contas")
async def enviar_prestacao_contas(
    os_id: UUID,
    body: SettlementSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Colaborador envia a prestação de contas ao finalizar o serviço.
    Registra os gastos reais, calcula o saldo e envia ao financeiro para aceite.
    """
    os = await get_os_or_404(db, str(os_id))

    if os.collaborator_id != str(current_user.user_id) and current_user.role not in ("admin", "financeiro"):
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    if os.status != "em_execucao":
        raise HTTPException(status_code=409, detail="Prestação de contas só pode ser enviada em 'em_execucao'")

    if not body.items:
        raise HTTPException(status_code=400, detail="Informe ao menos um item de gasto")

    # Inserir itens da prestação de contas
    for item in body.items:
        await db.execute(
            text("""
                INSERT INTO os_account_items
                    (service_order_id, advance_type_id, description, amount, receipt_url)
                VALUES
                    (:os_id, :advance_type_id, :description, :amount, :receipt_url)
            """),
            {
                "os_id": str(os_id),
                "advance_type_id": item.advance_type_id,
                "description": item.description,
                "amount": item.amount,
                "receipt_url": item.receipt_url,
            },
        )

    # Calcular total gasto e saldo
    spent_result = await db.execute(
        text("SELECT coalesce(sum(amount), 0) FROM os_account_items WHERE service_order_id = :os_id"),
        {"os_id": str(os_id)},
    )
    spent_total = float(spent_result.scalar())
    advances_total = os.advances_total
    balance = round(spent_total - advances_total, 2)

    # Determinar settlement_status
    if balance > 0:
        settlement_status = "reembolso_pendente"   # empresa deve ao colaborador
    elif balance < 0:
        settlement_status = "em_aberto"             # colaborador deve devolver
    else:
        settlement_status = "em_aberto"             # zerado, aguarda aceite

    await db.execute(
        text("""
            UPDATE service_orders SET
                status = 'aguardando_aceite',
                spent_total = :spent_total,
                balance = :balance,
                settlement_status = :settlement_status,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "id": str(os_id),
            "spent_total": spent_total,
            "balance": balance,
            "settlement_status": settlement_status,
        },
    )
    return await get_os_or_404(db, str(os_id))


@router.post("/{os_id}/aceitar-prestacao", response_model=OSResponse, summary="Financeiro aceita prestação de contas")
async def aceitar_prestacao(
    os_id: UUID,
    body: SettlementReview,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_financeiro),
):
    """
    Financeiro analisa e aceita ou recusa a prestação de contas.
    Se aceitar e houver saldo a devolver, OS fica 'pendente_devolucao'.
    Se aceitar e houver reembolso, OS fica 'reembolso_pendente'.
    Se aceitar e saldo zerado, encerra a OS.
    Se recusar, devolve ao colaborador.
    """
    os = await get_os_or_404(db, str(os_id))
    if os.status != "aguardando_aceite":
        raise HTTPException(status_code=409, detail="O.S. não está aguardando aceite")

    if not body.approved:
        if not body.notes:
            raise HTTPException(status_code=400, detail="Justificativa obrigatória ao recusar")
        await db.execute(
            text("""
                UPDATE service_orders SET
                    status = 'devolvida',
                    rejection_reason = :notes,
                    updated_at = now()
                WHERE id = :id
            """),
            {"id": str(os_id), "notes": body.notes},
        )
        return await get_os_or_404(db, str(os_id))

    # Aceito — definir próximo status com base no saldo
    balance = os.balance or 0
    if balance < 0:
        # Colaborador deve devolver — ativa contadores de prazo
        new_status = "aguardando_aceite"   # encerrada após devolução física
        settlement_status = "pendente_devolucao"
        os_status = "em_execucao"          # mantém aberta até devolução
    elif balance > 0:
        # Empresa deve reembolsar
        settlement_status = "reembolso_pendente"
        os_status = "encerrada"
    else:
        # Zerado — encerra direto
        settlement_status = "devolvido"
        os_status = "encerrada"

    await db.execute(
        text("""
            UPDATE service_orders SET
                status = :os_status,
                settlement_status = :settlement_status,
                settlement_notes = :notes,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "id": str(os_id),
            "os_status": os_status,
            "settlement_status": settlement_status,
            "notes": body.notes,
        },
    )
    return await get_os_or_404(db, str(os_id))


@router.post("/{os_id}/registrar-devolucao", response_model=OSResponse, summary="Registrar devolução física de adiantamento")
async def registrar_devolucao(
    os_id: UUID,
    body: SettlementClose,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_financeiro),
):
    """
    Financeiro confirma que o colaborador devolveu fisicamente o saldo.
    Encerra a O.S. e remove o bloqueio do colaborador (via trigger no banco).
    """
    os = await get_os_or_404(db, str(os_id))
    if os.settlement_status != "pendente_devolucao":
        raise HTTPException(status_code=409, detail="O.S. não está com devolução pendente")

    await db.execute(
        text("""
            UPDATE service_orders SET
                status = 'encerrada',
                settlement_status = 'devolvido',
                settled_at = now(),
                settled_by = :settled_by,
                settlement_proof_url = :proof_url,
                settlement_notes = :notes,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "id": str(os_id),
            "settled_by": str(current_user.user_id),
            "proof_url": body.settlement_proof_url,
            "notes": body.settlement_notes,
        },
    )
    # O trigger check_collaborator_block no banco cuida do desbloqueio automático
    return await get_os_or_404(db, str(os_id))


# ---------------------------------------------------------------------------
# Endpoint — Log de auditoria
# ---------------------------------------------------------------------------

@router.get("/{os_id}/auditoria", response_model=list[OSAuditEntry], summary="Histórico de auditoria da O.S.")
async def auditoria_os(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                al.id::text,
                al.from_status,
                al.to_status,
                al.changed_by::text,
                p.full_name as changed_by_name,
                al.notes,
                al.created_at::text
            FROM os_audit_log al
            LEFT JOIN profiles p ON p.id = al.changed_by
            WHERE al.service_order_id = :os_id
            ORDER BY al.created_at
        """),
        {"os_id": str(os_id)},
    )
    return [OSAuditEntry(**dict(r._mapping)) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Endpoint — Itens da prestação de contas
# ---------------------------------------------------------------------------

@router.get("/{os_id}/prestacao-de-contas/itens", response_model=list[AccountItemResponse], summary="Itens da prestação de contas")
async def itens_prestacao(
    os_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    os = await get_os_or_404(db, str(os_id))
    if current_user.role == "colaborador" and os.collaborator_id != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    result = await db.execute(
        text("""
            SELECT
                id::text, service_order_id::text,
                advance_type_id::text, description,
                amount, receipt_url, created_at::text
            FROM os_account_items
            WHERE service_order_id = :os_id
            ORDER BY created_at
        """),
        {"os_id": str(os_id)},
    )
    return [AccountItemResponse(**dict(r._mapping)) for r in result.fetchall()]
