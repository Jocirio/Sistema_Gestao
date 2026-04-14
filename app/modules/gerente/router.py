from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_gerente, require_financeiro, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/gerente", tags=["gerente"])


# ---------------------------------------------------------------------------
# Schemas — Produtos e implantação
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    name: str
    description: str | None = None


class ProductResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_active: bool
    created_at: str


class ClientProductCreate(BaseModel):
    product_id: str
    started_at: str | None = None
    notes: str | None = None


class ClientProductResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    product_id: str
    product_name: str
    started_at: str | None
    notes: str | None
    created_at: str
    # Progresso
    total_items: int = 0
    completed_items: int = 0
    completion_pct: float = 0.0


class PlanCreate(BaseModel):
    title: str


class PlanResponse(BaseModel):
    id: str
    client_product_id: str
    title: str
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str


class ChecklistItemCreate(BaseModel):
    title: str
    order_index: int = 0


class ChecklistItemResponse(BaseModel):
    id: str
    plan_id: str
    title: str
    order_index: int
    completed: bool
    completed_by: str | None
    completed_by_name: str | None
    completed_at: str | None
    created_at: str


class ChecklistItemComplete(BaseModel):
    completed: bool


# ---------------------------------------------------------------------------
# Schemas — SLA
# ---------------------------------------------------------------------------

class SLAConfigCreate(BaseModel):
    sector_id: str | None = None
    label: str
    max_days: int
    alert_days_before: int = 2


class SLAConfigResponse(BaseModel):
    id: str
    sector_id: str | None
    sector_name: str | None
    label: str
    max_days: int
    alert_days_before: int
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Estoque
# ---------------------------------------------------------------------------

class StockItemCreate(BaseModel):
    name: str
    unit: str = "un"
    quantity: float = 0
    min_quantity: float = 0
    cost_per_unit: float | None = None


class StockItemResponse(BaseModel):
    id: str
    name: str
    unit: str
    quantity: float
    min_quantity: float
    cost_per_unit: float | None
    below_minimum: bool
    created_at: str
    updated_at: str


class StockMovementCreate(BaseModel):
    quantity: float          # negativo = saída, positivo = entrada
    movement_type: str       # entrada, saida_os, ajuste
    service_order_id: str | None = None
    notes: str | None = None


class StockMovementResponse(BaseModel):
    id: str
    stock_item_id: str
    stock_item_name: str
    service_order_id: str | None
    os_number: str | None
    quantity: float
    movement_type: str
    notes: str | None
    created_by: str
    created_by_name: str
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Projetos finalizados → financeiro
# ---------------------------------------------------------------------------

class ProjectFinalize(BaseModel):
    service_order_id: str
    notes: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_checklist_item(row) -> ChecklistItemResponse:
    m = dict(row._mapping)
    return ChecklistItemResponse(
        id=str(m["id"]),
        plan_id=str(m["plan_id"]),
        title=m["title"],
        order_index=m["order_index"],
        completed=m["completed"],
        completed_by=str(m["completed_by"]) if m.get("completed_by") else None,
        completed_by_name=m.get("completed_by_name"),
        completed_at=str(m["completed_at"]) if m.get("completed_at") else None,
        created_at=str(m["created_at"]),
    )


def row_to_stock_item(row) -> StockItemResponse:
    m = dict(row._mapping)
    return StockItemResponse(
        id=str(m["id"]),
        name=m["name"],
        unit=m["unit"],
        quantity=float(m["quantity"]),
        min_quantity=float(m["min_quantity"]),
        cost_per_unit=float(m["cost_per_unit"]) if m.get("cost_per_unit") else None,
        below_minimum=float(m["quantity"]) < float(m["min_quantity"]),
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Produtos
# ---------------------------------------------------------------------------

@router.get("/produtos", response_model=list[ProductResponse], summary="Listar produtos")
async def listar_produtos(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id::text, name, description, is_active, created_at::text FROM products ORDER BY name")
    )
    return [ProductResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/produtos", response_model=ProductResponse, status_code=201, summary="Criar produto")
async def criar_produto(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO products (name, description)
            VALUES (:name, :description)
            RETURNING id::text, name, description, is_active, created_at::text
        """),
        body.model_dump(),
    )
    return ProductResponse(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Produtos por cliente (implantação)
# ---------------------------------------------------------------------------

@router.get(
    "/clientes/{client_id}/produtos",
    response_model=list[ClientProductResponse],
    summary="Produtos implantados no cliente",
)
async def listar_produtos_cliente(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                cp.id::text,
                cp.client_id::text,
                cl.name             as client_name,
                cp.product_id::text,
                pr.name             as product_name,
                cp.started_at::text,
                cp.notes,
                cp.created_at::text,
                coalesce(ip.total_items, 0)      as total_items,
                coalesce(ip.completed_items, 0)  as completed_items,
                coalesce(ip.completion_pct, 0)   as completion_pct
            FROM client_products cp
            JOIN clients cl  ON cl.id = cp.client_id
            JOIN products pr ON pr.id = cp.product_id
            LEFT JOIN implementation_progress ip
                ON ip.client_id = cp.client_id AND ip.product_id = cp.product_id
            WHERE cp.client_id = :client_id
            ORDER BY pr.name
        """),
        {"client_id": str(client_id)},
    )
    rows = result.fetchall()
    items = []
    for r in rows:
        m = dict(r._mapping)
        items.append(ClientProductResponse(
            id=str(m["id"]),
            client_id=str(m["client_id"]),
            client_name=m["client_name"],
            product_id=str(m["product_id"]),
            product_name=m["product_name"],
            started_at=str(m["started_at"]) if m.get("started_at") else None,
            notes=m.get("notes"),
            created_at=str(m["created_at"]),
            total_items=int(m["total_items"]),
            completed_items=int(m["completed_items"]),
            completion_pct=float(m["completion_pct"]),
        ))
    return items


@router.post(
    "/clientes/{client_id}/produtos",
    response_model=ClientProductResponse,
    status_code=201,
    summary="Vincular produto ao cliente",
)
async def vincular_produto(
    client_id: UUID,
    body: ClientProductCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO client_products (client_id, product_id, started_at, notes)
            VALUES (:client_id, :product_id, :started_at, :notes)
            RETURNING id::text
        """),
        {"client_id": str(client_id), **body.model_dump()},
    )
    cp_id = result.fetchone().id

    full = await db.execute(
        text("""
            SELECT
                cp.id::text, cp.client_id::text, cl.name as client_name,
                cp.product_id::text, pr.name as product_name,
                cp.started_at::text, cp.notes, cp.created_at::text,
                0 as total_items, 0 as completed_items, 0.0 as completion_pct
            FROM client_products cp
            JOIN clients cl  ON cl.id = cp.client_id
            JOIN products pr ON pr.id = cp.product_id
            WHERE cp.id = :id
        """),
        {"id": cp_id},
    )
    m = dict(full.fetchone()._mapping)
    return ClientProductResponse(**{
        **m,
        "id": str(m["id"]),
        "client_id": str(m["client_id"]),
        "product_id": str(m["product_id"]),
        "started_at": str(m["started_at"]) if m.get("started_at") else None,
        "created_at": str(m["created_at"]),
    })


# ---------------------------------------------------------------------------
# Endpoints — Planos de implantação e checklist
# ---------------------------------------------------------------------------

@router.get(
    "/client-products/{cp_id}/planos",
    response_model=list[PlanResponse],
    summary="Planos de implantação",
)
async def listar_planos(
    cp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                ip.id::text, ip.client_product_id::text,
                ip.title, ip.created_by::text,
                p.full_name as created_by_name,
                ip.created_at::text, ip.updated_at::text
            FROM implementation_plans ip
            LEFT JOIN profiles p ON p.id = ip.created_by
            WHERE ip.client_product_id = :cp_id
            ORDER BY ip.created_at
        """),
        {"cp_id": str(cp_id)},
    )
    rows = result.fetchall()
    return [
        PlanResponse(
            id=str(m["id"]),
            client_product_id=str(m["client_product_id"]),
            title=m["title"],
            created_by=str(m["created_by"]),
            created_by_name=m.get("created_by_name", ""),
            created_at=str(m["created_at"]),
            updated_at=str(m["updated_at"]),
        )
        for m in [dict(r._mapping) for r in rows]
    ]


@router.post(
    "/client-products/{cp_id}/planos",
    response_model=PlanResponse,
    status_code=201,
    summary="Criar plano de implantação",
)
async def criar_plano(
    cp_id: UUID,
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO implementation_plans (client_product_id, title, created_by)
            VALUES (:cp_id, :title, :created_by)
            RETURNING id::text, client_product_id::text, title, created_by::text, created_at::text, updated_at::text
        """),
        {"cp_id": str(cp_id), "title": body.title, "created_by": str(current_user.user_id)},
    )
    row = result.fetchone()
    m = dict(row._mapping)

    name_result = await db.execute(
        text("SELECT full_name FROM profiles WHERE id = :id"),
        {"id": str(current_user.user_id)},
    )
    name_row = name_result.fetchone()

    return PlanResponse(
        id=str(m["id"]),
        client_product_id=str(m["client_product_id"]),
        title=m["title"],
        created_by=str(m["created_by"]),
        created_by_name=name_row.full_name if name_row else "",
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
    )


@router.get(
    "/planos/{plan_id}/checklist",
    response_model=list[ChecklistItemResponse],
    summary="Itens do checklist",
)
async def listar_checklist(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Visível também no módulo colaborador para acompanhamento."""
    result = await db.execute(
        text("""
            SELECT
                ci.id::text, ci.plan_id::text, ci.title, ci.order_index,
                ci.completed, ci.completed_by::text,
                p.full_name as completed_by_name,
                ci.completed_at::text, ci.created_at::text
            FROM implementation_checklist_items ci
            LEFT JOIN profiles p ON p.id = ci.completed_by
            WHERE ci.plan_id = :plan_id
            ORDER BY ci.order_index, ci.created_at
        """),
        {"plan_id": str(plan_id)},
    )
    return [row_to_checklist_item(r) for r in result.fetchall()]


@router.post(
    "/planos/{plan_id}/checklist",
    response_model=ChecklistItemResponse,
    status_code=201,
    summary="Adicionar item ao checklist",
)
async def adicionar_item_checklist(
    plan_id: UUID,
    body: ChecklistItemCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO implementation_checklist_items (plan_id, title, order_index)
            VALUES (:plan_id, :title, :order_index)
            RETURNING id::text, plan_id::text, title, order_index, completed,
                      completed_by::text, completed_at::text, created_at::text
        """),
        {"plan_id": str(plan_id), **body.model_dump()},
    )
    row = result.fetchone()
    m = dict(row._mapping)
    m["completed_by_name"] = None
    return row_to_checklist_item(type("Row", (), {"_mapping": m})())


@router.patch(
    "/planos/{plan_id}/checklist/{item_id}",
    response_model=ChecklistItemResponse,
    summary="Marcar item do checklist",
)
async def marcar_item_checklist(
    plan_id: UUID,
    item_id: UUID,
    body: ChecklistItemComplete,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Colaborador ou gerente marcam itens do checklist como concluídos."""
    result = await db.execute(
        text("""
            UPDATE implementation_checklist_items SET
                completed    = :completed,
                completed_by = CASE WHEN :completed THEN :user_id::uuid ELSE null END,
                completed_at = CASE WHEN :completed THEN now() ELSE null END
            WHERE id = :item_id AND plan_id = :plan_id
            RETURNING id::text, plan_id::text, title, order_index, completed,
                      completed_by::text, completed_at::text, created_at::text
        """),
        {
            "completed": body.completed,
            "user_id": str(current_user.user_id),
            "item_id": str(item_id),
            "plan_id": str(plan_id),
        },
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    m = dict(row._mapping)
    if m.get("completed_by"):
        name_result = await db.execute(
            text("SELECT full_name FROM profiles WHERE id = :id"),
            {"id": m["completed_by"]},
        )
        name_row = name_result.fetchone()
        m["completed_by_name"] = name_row.full_name if name_row else None
    else:
        m["completed_by_name"] = None

    return row_to_checklist_item(type("Row", (), {"_mapping": m})())


@router.delete(
    "/planos/{plan_id}/checklist/{item_id}",
    status_code=204,
    summary="Remover item do checklist",
)
async def remover_item_checklist(
    plan_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("DELETE FROM implementation_checklist_items WHERE id = :id AND plan_id = :plan_id RETURNING id"),
        {"id": str(item_id), "plan_id": str(plan_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Item não encontrado")


# ---------------------------------------------------------------------------
# Endpoints — SLA
# ---------------------------------------------------------------------------

@router.get("/sla", response_model=list[SLAConfigResponse], summary="Listar configurações de SLA")
async def listar_sla(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                sc.id::text, sc.sector_id::text,
                s.name as sector_name,
                sc.label, sc.max_days, sc.alert_days_before,
                sc.is_active, sc.created_at::text
            FROM sla_configs sc
            LEFT JOIN os_sectors s ON s.id = sc.sector_id
            WHERE sc.is_active = true
            ORDER BY sc.label
        """)
    )
    return [
        SLAConfigResponse(**{**dict(r._mapping), "id": str(dict(r._mapping)["id"]),
                             "sector_id": str(dict(r._mapping)["sector_id"]) if dict(r._mapping).get("sector_id") else None})
        for r in result.fetchall()
    ]


@router.post("/sla", response_model=SLAConfigResponse, status_code=201, summary="Criar SLA")
async def criar_sla(
    body: SLAConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO sla_configs (sector_id, label, max_days, alert_days_before)
            VALUES (:sector_id, :label, :max_days, :alert_days_before)
            RETURNING id::text, sector_id::text, label, max_days, alert_days_before, is_active, created_at::text
        """),
        body.model_dump(),
    )
    m = dict(result.fetchone()._mapping)
    m["sector_name"] = None
    return SLAConfigResponse(**m)


@router.get("/sla/alertas", summary="O.S. com SLA próximo do vencimento")
async def alertas_sla(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Lista O.S. em execução cujo prazo de SLA está próximo do vencimento
    ou já ultrapassado.
    """
    result = await db.execute(
        text("""
            SELECT
                so.id::text,
                so.os_number,
                so.collaborator_id::text,
                p.full_name         as collaborator_name,
                so.client_id::text,
                cl.name             as client_name,
                so.departure_date::text,
                so.status,
                sc.label            as sla_label,
                sc.max_days,
                sc.alert_days_before,
                so.departure_date + sc.max_days as sla_deadline,
                (so.departure_date + sc.max_days - current_date) as days_remaining
            FROM service_orders so
            JOIN profiles p     ON p.id  = so.collaborator_id
            JOIN clients cl     ON cl.id = so.client_id
            JOIN sla_configs sc ON sc.sector_id = so.sector_id AND sc.is_active = true
            WHERE so.status = 'em_execucao'
            AND (so.departure_date + sc.max_days - current_date) <= sc.alert_days_before
            ORDER BY days_remaining
        """)
    )
    return [dict(r._mapping) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Endpoints — Estoque
# ---------------------------------------------------------------------------

@router.get("/estoque", response_model=list[StockItemResponse], summary="Listar estoque")
async def listar_estoque(
    abaixo_minimo: bool | None = Query(None, description="Filtrar itens abaixo do mínimo"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if abaixo_minimo:
        conditions.append("quantity < min_quantity")

    result = await db.execute(
        text(f"""
            SELECT id::text, name, unit, quantity, min_quantity, cost_per_unit,
                   created_at::text, updated_at::text
            FROM stock_items
            WHERE {" AND ".join(conditions)}
            ORDER BY name
        """),
        params,
    )
    return [row_to_stock_item(r) for r in result.fetchall()]


@router.post("/estoque", response_model=StockItemResponse, status_code=201, summary="Criar item de estoque")
async def criar_item_estoque(
    body: StockItemCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("""
            INSERT INTO stock_items (name, unit, quantity, min_quantity, cost_per_unit)
            VALUES (:name, :unit, :quantity, :min_quantity, :cost_per_unit)
            RETURNING id::text, name, unit, quantity, min_quantity,
                      cost_per_unit, created_at::text, updated_at::text
        """),
        body.model_dump(),
    )
    return row_to_stock_item(result.fetchone())


@router.post(
    "/estoque/{item_id}/movimentar",
    response_model=StockMovementResponse,
    status_code=201,
    summary="Movimentar estoque",
)
async def movimentar_estoque(
    item_id: UUID,
    body: StockMovementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_gerente),
):
    """
    Registra entrada ou saída de estoque.
    Para saídas vinculadas a O.S., quantity deve ser negativo.
    O trigger no banco atualiza o saldo automaticamente.
    """
    valid_types = {"entrada", "saida_os", "ajuste"}
    if body.movement_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(valid_types)}")

    # Verificar se saída não deixa estoque negativo
    if body.quantity < 0:
        current = await db.execute(
            text("SELECT quantity FROM stock_items WHERE id = :id"),
            {"id": str(item_id)},
        )
        row = current.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item não encontrado")
        if float(row.quantity) + body.quantity < 0:
            raise HTTPException(
                status_code=409,
                detail=f"Saldo insuficiente. Atual: {row.quantity}",
            )

    result = await db.execute(
        text("""
            INSERT INTO stock_movements
                (stock_item_id, service_order_id, quantity, movement_type, notes, created_by)
            VALUES
                (:item_id, :service_order_id, :quantity, :movement_type, :notes, :created_by)
            RETURNING id::text, stock_item_id::text, service_order_id::text,
                      quantity, movement_type, notes, created_by::text, created_at::text
        """),
        {
            "item_id": str(item_id),
            "service_order_id": body.service_order_id,
            "quantity": body.quantity,
            "movement_type": body.movement_type,
            "notes": body.notes,
            "created_by": str(current_user.user_id),
        },
    )
    row = result.fetchone()
    m = dict(row._mapping)

    # Buscar dados complementares
    item_result = await db.execute(
        text("SELECT name FROM stock_items WHERE id = :id"), {"id": str(item_id)}
    )
    item_row = item_result.fetchone()

    name_result = await db.execute(
        text("SELECT full_name FROM profiles WHERE id = :id"),
        {"id": str(current_user.user_id)},
    )
    name_row = name_result.fetchone()

    os_number = None
    if m.get("service_order_id"):
        os_result = await db.execute(
            text("SELECT os_number FROM service_orders WHERE id = :id"),
            {"id": m["service_order_id"]},
        )
        os_row = os_result.fetchone()
        os_number = os_row.os_number if os_row else None

    return StockMovementResponse(
        id=str(m["id"]),
        stock_item_id=str(m["stock_item_id"]),
        stock_item_name=item_row.name if item_row else "",
        service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
        os_number=os_number,
        quantity=float(m["quantity"]),
        movement_type=m["movement_type"],
        notes=m.get("notes"),
        created_by=str(m["created_by"]),
        created_by_name=name_row.full_name if name_row else "",
        created_at=str(m["created_at"]),
    )


@router.get("/estoque/{item_id}/historico", response_model=list[StockMovementResponse], summary="Histórico de movimentações")
async def historico_estoque(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                sm.id::text, sm.stock_item_id::text,
                si.name             as stock_item_name,
                sm.service_order_id::text,
                so.os_number,
                sm.quantity, sm.movement_type, sm.notes,
                sm.created_by::text,
                p.full_name         as created_by_name,
                sm.created_at::text
            FROM stock_movements sm
            JOIN stock_items si      ON si.id = sm.stock_item_id
            LEFT JOIN service_orders so ON so.id = sm.service_order_id
            LEFT JOIN profiles p     ON p.id  = sm.created_by
            WHERE sm.stock_item_id = :item_id
            ORDER BY sm.created_at DESC
        """),
        {"item_id": str(item_id)},
    )
    return [
        StockMovementResponse(
            id=str(m["id"]),
            stock_item_id=str(m["stock_item_id"]),
            stock_item_name=m["stock_item_name"],
            service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
            os_number=m.get("os_number"),
            quantity=float(m["quantity"]),
            movement_type=m["movement_type"],
            notes=m.get("notes"),
            created_by=str(m["created_by"]),
            created_by_name=m.get("created_by_name", ""),
            created_at=str(m["created_at"]),
        )
        for m in [dict(r._mapping) for r in result.fetchall()]
    ]


# ---------------------------------------------------------------------------
# Endpoints — Alertas de período aquisitivo de férias
# ---------------------------------------------------------------------------

@router.get("/alertas/ferias-aquisitivo", summary="Colaboradores com período aquisitivo atingido")
async def alertas_ferias(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Lista colaboradores que atingiram ou estão próximos (30 dias) do período
    aquisitivo de férias (365 dias de trabalho sem tirar férias).
    Considera a data de criação do perfil como data de admissão simplificada.
    """
    result = await db.execute(
        text("""
            SELECT
                p.id::text,
                p.full_name,
                p.created_at::date              as admission_date,
                date_part('day', now() - p.created_at)::integer as days_since_admission,
                (date_part('day', now() - p.created_at) / 365)::integer as acquisition_years,
                exists (
                    select 1 from vacation_requests vr
                    where vr.collaborator_id = p.id
                    and vr.status = 'aprovada'
                    and vr.start_date >= (now() - interval '365 days')::date
                ) as had_recent_vacation
            FROM profiles p
            WHERE p.role = 'colaborador'
            AND p.is_active = true
            AND date_part('day', now() - p.created_at) >= 335
            ORDER BY days_since_admission DESC
        """)
    )
    return [dict(r._mapping) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Endpoints — Finalizar projeto e enviar ao financeiro
# ---------------------------------------------------------------------------

@router.post("/projetos/finalizar", summary="Finalizar projeto e enviar ao financeiro")
async def finalizar_projeto(
    body: ProjectFinalize,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_gerente),
):
    """
    Marca a O.S. como projeto finalizado e envia notificação ao financeiro
    para iniciar o processo de cobrança/faturamento.
    """
    # Verificar que a OS está encerrada
    result = await db.execute(
        text("SELECT id, os_number, client_id, status FROM service_orders WHERE id = :id"),
        {"id": body.service_order_id},
    )
    os = result.fetchone()
    if not os:
        raise HTTPException(status_code=404, detail="O.S. não encontrada")

    if os.status != "encerrada":
        raise HTTPException(
            status_code=409,
            detail=f"O.S. está em '{os.status}' — apenas O.S. encerrada pode ser finalizada como projeto",
        )

    # Criar lançamento de contas a receber no financeiro
    # (o financeiro visualiza e complementa conforme necessário)
    await db.execute(
        text("""
            INSERT INTO financial_entries
                (type, description, amount, due_date, client_id, service_order_id, status, created_by)
            SELECT
                'receber',
                'Projeto finalizado — ' || so.os_number,
                coalesce(cl.contract_value, 0),
                current_date + 30,
                so.client_id,
                so.id,
                'pendente',
                :created_by
            FROM service_orders so
            JOIN clients cl ON cl.id = so.client_id
            WHERE so.id = :os_id
        """),
        {
            "os_id": body.service_order_id,
            "created_by": str(current_user.user_id),
        },
    )

    return {
        "message": "Projeto enviado ao financeiro com sucesso",
        "os_number": os.os_number,
        "notes": body.notes,
    }


# ---------------------------------------------------------------------------
# Endpoints — Dashboard do gerente
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Dashboard do gerente")
async def dashboard_gerente(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """KPIs consolidados para o painel do gerente."""

    # OS por status
    os_result = await db.execute(
        text("""
            SELECT status, count(*) as total
            FROM service_orders
            GROUP BY status
        """)
    )
    os_por_status = {r.status: r.total for r in os_result.fetchall()}

    # Colaboradores bloqueados
    blocked_result = await db.execute(
        text("SELECT count(*) FROM profiles WHERE os_blocked = true AND is_active = true")
    )
    colaboradores_bloqueados = blocked_result.scalar()

    # Estoque abaixo do mínimo
    stock_result = await db.execute(
        text("SELECT count(*) FROM stock_items WHERE quantity < min_quantity")
    )
    estoque_critico = stock_result.scalar()

    # Férias pendentes de aprovação
    ferias_result = await db.execute(
        text("SELECT count(*) FROM vacation_requests WHERE status = 'solicitada'")
    )
    ferias_pendentes = ferias_result.scalar()

    # SLA em risco
    sla_result = await db.execute(
        text("""
            SELECT count(*) FROM service_orders so
            JOIN sla_configs sc ON sc.sector_id = so.sector_id AND sc.is_active = true
            WHERE so.status = 'em_execucao'
            AND (so.departure_date + sc.max_days - current_date) <= sc.alert_days_before
        """)
    )
    sla_em_risco = sla_result.scalar()

    # Clientes ativos
    clientes_result = await db.execute(
        text("SELECT count(*) FROM clients WHERE is_active = true")
    )
    clientes_ativos = clientes_result.scalar()

    return {
        "os_por_status": os_por_status,
        "colaboradores_bloqueados": colaboradores_bloqueados,
        "estoque_critico": estoque_critico,
        "ferias_pendentes": ferias_pendentes,
        "sla_em_risco": sla_em_risco,
        "clientes_ativos": clientes_ativos,
    }
