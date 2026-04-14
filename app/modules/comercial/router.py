from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_comercial, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/comercial", tags=["comercial"])


# ---------------------------------------------------------------------------
# Schemas — Workflow de clientes
# ---------------------------------------------------------------------------

class WorkflowStageResponse(BaseModel):
    id: str
    name: str
    order_index: int
    color: str | None
    is_active: bool


class ClientWorkflowResponse(BaseModel):
    client_id: str
    client_name: str
    client_city: str | None
    client_state: str | None
    stage_id: str
    stage_name: str
    stage_order: int
    assigned_to: str | None
    assigned_name: str | None
    notes: str | None
    updated_at: str


class ClientWorkflowMove(BaseModel):
    stage_id: str
    assigned_to: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Schemas — Atividades com clientes
# ---------------------------------------------------------------------------

class ActivityCreate(BaseModel):
    client_id: str
    type: str          # visita, apresentacao, orcamento, documento, ligacao, outro
    title: str
    description: str | None = None
    occurred_at: str | None = None   # ISO datetime, padrão = now
    attachment_url: str | None = None


class ActivityResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    type: str
    title: str
    description: str | None
    occurred_at: str
    created_by: str
    created_by_name: str
    attachment_url: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Orçamentos
# ---------------------------------------------------------------------------

class QuoteCreate(BaseModel):
    client_id: str
    title: str
    value: float
    valid_until: str | None = None
    notes: str | None = None
    file_url: str | None = None


class QuoteUpdate(BaseModel):
    title: str | None = None
    value: float | None = None
    status: str | None = None    # enviado, aprovado, perdido, expirado
    valid_until: str | None = None
    notes: str | None = None
    file_url: str | None = None
    responded_at: str | None = None


class QuoteResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    title: str
    value: float
    status: str
    sent_at: str | None
    responded_at: str | None
    valid_until: str | None
    notes: str | None
    file_url: str | None
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Schemas — Solicitação de diária
# ---------------------------------------------------------------------------

class DailyRequestCreate(BaseModel):
    destination: str
    departure_date: str
    return_date: str
    purpose: str
    estimated_value: float | None = None


class DailyRequestResponse(BaseModel):
    id: str
    requested_by: str
    requested_by_name: str
    destination: str
    departure_date: str
    return_date: str
    purpose: str
    estimated_value: float | None
    status: str
    reviewed_by: str | None
    reviewed_by_name: str | None
    reviewed_at: str | None
    review_notes: str | None
    approved_value: float | None
    created_at: str


class DailyRequestReview(BaseModel):
    approved: bool
    approved_value: float | None = None
    review_notes: str | None = None


# ---------------------------------------------------------------------------
# Schemas — Entrega ao gerente (handover)
# ---------------------------------------------------------------------------

class HandoverCreate(BaseModel):
    client_id: str
    to_profile: str          # ID do gerente
    contract_url: str | None = None
    service_details: str | None = None
    notes: str | None = None


class HandoverResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    from_profile: str
    from_name: str
    to_profile: str
    to_name: str
    contract_url: str | None
    service_details: str | None
    notes: str | None
    status: str
    rejection_reason: str | None
    created_at: str
    updated_at: str


class HandoverReview(BaseModel):
    accepted: bool
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_activity(row) -> ActivityResponse:
    m = dict(row._mapping)
    return ActivityResponse(
        id=str(m["id"]),
        client_id=str(m["client_id"]),
        client_name=m.get("client_name", ""),
        type=m["type"],
        title=m["title"],
        description=m.get("description"),
        occurred_at=str(m["occurred_at"]),
        created_by=str(m["created_by"]),
        created_by_name=m.get("created_by_name", ""),
        attachment_url=m.get("attachment_url"),
        created_at=str(m["created_at"]),
    )


def row_to_quote(row) -> QuoteResponse:
    m = dict(row._mapping)
    return QuoteResponse(
        id=str(m["id"]),
        client_id=str(m["client_id"]),
        client_name=m.get("client_name", ""),
        title=m["title"],
        value=float(m["value"]),
        status=m["status"],
        sent_at=str(m["sent_at"]) if m.get("sent_at") else None,
        responded_at=str(m["responded_at"]) if m.get("responded_at") else None,
        valid_until=str(m["valid_until"]) if m.get("valid_until") else None,
        notes=m.get("notes"),
        file_url=m.get("file_url"),
        created_by=str(m["created_by"]),
        created_by_name=m.get("created_by_name", ""),
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
    )


def row_to_handover(row) -> HandoverResponse:
    m = dict(row._mapping)
    return HandoverResponse(
        id=str(m["id"]),
        client_id=str(m["client_id"]),
        client_name=m.get("client_name", ""),
        from_profile=str(m["from_profile"]),
        from_name=m.get("from_name", ""),
        to_profile=str(m["to_profile"]),
        to_name=m.get("to_name", ""),
        contract_url=m.get("contract_url"),
        service_details=m.get("service_details"),
        notes=m.get("notes"),
        status=m["status"],
        rejection_reason=m.get("rejection_reason"),
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
    )


def row_to_daily(row) -> DailyRequestResponse:
    m = dict(row._mapping)
    return DailyRequestResponse(
        id=str(m["id"]),
        requested_by=str(m["requested_by"]),
        requested_by_name=m.get("requested_by_name", ""),
        destination=m["destination"],
        departure_date=str(m["departure_date"]),
        return_date=str(m["return_date"]),
        purpose=m["purpose"],
        estimated_value=float(m["estimated_value"]) if m.get("estimated_value") else None,
        status=m["status"],
        reviewed_by=str(m["reviewed_by"]) if m.get("reviewed_by") else None,
        reviewed_by_name=m.get("reviewed_by_name"),
        reviewed_at=str(m["reviewed_at"]) if m.get("reviewed_at") else None,
        review_notes=m.get("review_notes"),
        approved_value=float(m["approved_value"]) if m.get("approved_value") else None,
        created_at=str(m["created_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Workflow de clientes (Kanban)
# ---------------------------------------------------------------------------

@router.get("/workflow/stages", response_model=list[WorkflowStageResponse], summary="Listar estágios do funil")
async def listar_stages(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT id::text, name, order_index, color, is_active
            FROM workflow_stages
            WHERE is_active = true
            ORDER BY order_index
        """)
    )
    return [WorkflowStageResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.get("/workflow/kanban", response_model=list[ClientWorkflowResponse], summary="Kanban de clientes")
async def kanban(
    stage_id: str | None = Query(None, description="Filtrar por estágio"),
    assigned_to: str | None = Query(None, description="Filtrar por responsável"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """
    Retorna todos os clientes no funil comercial com o estágio atual.
    Use para montar o Kanban no frontend.
    """
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if stage_id:
        conditions.append("cw.stage_id = :stage_id")
        params["stage_id"] = stage_id

    if assigned_to:
        conditions.append("cw.assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to

    where = " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT
                cw.client_id::text,
                cl.name             as client_name,
                cl.city             as client_city,
                cl.state            as client_state,
                cw.stage_id::text,
                ws.name             as stage_name,
                ws.order_index      as stage_order,
                cw.assigned_to::text,
                p.full_name         as assigned_name,
                cw.notes,
                cw.updated_at::text
            FROM client_workflow cw
            JOIN clients cl         ON cl.id  = cw.client_id
            JOIN workflow_stages ws ON ws.id  = cw.stage_id
            LEFT JOIN profiles p    ON p.id   = cw.assigned_to
            WHERE {where} AND cl.is_active = true
            ORDER BY ws.order_index, cl.name
        """),
        params,
    )
    return [
        ClientWorkflowResponse(**dict(r._mapping))
        for r in result.fetchall()
    ]


@router.post("/workflow/{client_id}/mover", response_model=ClientWorkflowResponse, summary="Mover cliente no funil")
async def mover_cliente(
    client_id: UUID,
    body: ClientWorkflowMove,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Move um cliente para outro estágio do funil.
    Cria o registro de workflow se o cliente ainda não estiver no funil.
    """
    result = await db.execute(
        text("""
            INSERT INTO client_workflow (client_id, stage_id, assigned_to, notes)
            VALUES (:client_id, :stage_id, :assigned_to, :notes)
            ON CONFLICT (client_id) DO UPDATE SET
                stage_id    = EXCLUDED.stage_id,
                assigned_to = EXCLUDED.assigned_to,
                notes       = EXCLUDED.notes,
                updated_at  = now()
            RETURNING
                client_id::text, stage_id::text, assigned_to::text, notes, updated_at::text
        """),
        {
            "client_id": str(client_id),
            "stage_id": body.stage_id,
            "assigned_to": body.assigned_to,
            "notes": body.notes,
        },
    )
    row = result.fetchone()

    # Buscar dados completos
    full = await db.execute(
        text("""
            SELECT
                cw.client_id::text, cl.name as client_name,
                cl.city as client_city, cl.state as client_state,
                cw.stage_id::text, ws.name as stage_name, ws.order_index as stage_order,
                cw.assigned_to::text, p.full_name as assigned_name,
                cw.notes, cw.updated_at::text
            FROM client_workflow cw
            JOIN clients cl         ON cl.id  = cw.client_id
            JOIN workflow_stages ws ON ws.id  = cw.stage_id
            LEFT JOIN profiles p    ON p.id   = cw.assigned_to
            WHERE cw.client_id = :client_id
        """),
        {"client_id": str(client_id)},
    )
    return ClientWorkflowResponse(**dict(full.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Atividades com clientes (histórico de relacionamento)
# ---------------------------------------------------------------------------

ACTIVITY_SELECT = """
    SELECT
        ca.id::text,
        ca.client_id::text,
        cl.name         as client_name,
        ca.type,
        ca.title,
        ca.description,
        ca.occurred_at::text,
        ca.created_by::text,
        p.full_name     as created_by_name,
        ca.attachment_url,
        ca.created_at::text
    FROM client_activities ca
    JOIN clients cl     ON cl.id = ca.client_id
    LEFT JOIN profiles p ON p.id = ca.created_by
"""


@router.get("/atividades", response_model=Page[ActivityResponse], summary="Listar atividades")
async def listar_atividades(
    client_id: str | None = Query(None),
    type: str | None = Query(None, description="visita, apresentacao, orcamento, documento, ligacao, outro"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if client_id:
        conditions.append("ca.client_id = :client_id")
        params["client_id"] = client_id

    if type:
        conditions.append("ca.type = :type")
        params["type"] = type

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM client_activities ca WHERE {where}"),
        params,
    )
    total = count.scalar()

    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{ACTIVITY_SELECT} WHERE {where} ORDER BY ca.occurred_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_activity(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("/atividades", response_model=ActivityResponse, status_code=201, summary="Registrar atividade")
async def criar_atividade(
    body: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Registra uma atividade no histórico de relacionamento com o cliente."""
    valid_types = {"visita", "apresentacao", "orcamento", "documento", "ligacao", "outro"}
    if body.type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(valid_types)}")

    result = await db.execute(
        text("""
            INSERT INTO client_activities
                (client_id, type, title, description, occurred_at, created_by, attachment_url)
            VALUES
                (:client_id, :type, :title, :description,
                 coalesce(:occurred_at::timestamptz, now()),
                 :created_by, :attachment_url)
            RETURNING id::text
        """),
        {
            **body.model_dump(),
            "created_by": str(current_user.user_id),
        },
    )
    activity_id = result.fetchone().id

    full = await db.execute(
        text(f"{ACTIVITY_SELECT} WHERE ca.id = :id"),
        {"id": activity_id},
    )
    return row_to_activity(full.fetchone())


@router.delete("/atividades/{activity_id}", status_code=204, summary="Remover atividade")
async def remover_atividade(
    activity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Somente quem criou ou admin pode remover."""
    result = await db.execute(
        text("""
            DELETE FROM client_activities
            WHERE id = :id
            AND (:role = 'admin' OR created_by = :uid)
            RETURNING id
        """),
        {"id": str(activity_id), "role": current_user.role, "uid": str(current_user.user_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Atividade não encontrada ou sem permissão")


# ---------------------------------------------------------------------------
# Endpoints — Orçamentos
# ---------------------------------------------------------------------------

QUOTE_SELECT = """
    SELECT
        q.id::text,
        q.client_id::text,
        cl.name         as client_name,
        q.title,
        q.value,
        q.status,
        q.sent_at::text,
        q.responded_at::text,
        q.valid_until::text,
        q.notes,
        q.file_url,
        q.created_by::text,
        p.full_name     as created_by_name,
        q.created_at::text,
        q.updated_at::text
    FROM quotes q
    JOIN clients cl      ON cl.id = q.client_id
    LEFT JOIN profiles p ON p.id  = q.created_by
"""


@router.get("/orcamentos", response_model=Page[QuoteResponse], summary="Listar orçamentos")
async def listar_orcamentos(
    client_id: str | None = Query(None),
    status: str | None = Query(None, description="enviado, aprovado, perdido, expirado"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if client_id:
        conditions.append("q.client_id = :client_id")
        params["client_id"] = client_id

    if status:
        conditions.append("q.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM quotes q WHERE {where}"), params
    )
    total = count.scalar()
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{QUOTE_SELECT} WHERE {where} ORDER BY q.created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_quote(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("/orcamentos", response_model=QuoteResponse, status_code=201, summary="Criar orçamento")
async def criar_orcamento(
    body: QuoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            INSERT INTO quotes
                (client_id, title, value, valid_until, notes, file_url, sent_at, created_by)
            VALUES
                (:client_id, :title, :value, :valid_until, :notes, :file_url, now(), :created_by)
            RETURNING id::text
        """),
        {**body.model_dump(), "created_by": str(current_user.user_id)},
    )
    quote_id = result.fetchone().id

    full = await db.execute(text(f"{QUOTE_SELECT} WHERE q.id = :id"), {"id": quote_id})
    return row_to_quote(full.fetchone())


@router.patch("/orcamentos/{quote_id}", response_model=QuoteResponse, summary="Atualizar orçamento")
async def atualizar_orcamento(
    quote_id: UUID,
    body: QuoteUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    valid_statuses = {"enviado", "aprovado", "perdido", "expirado"}
    if body.status and body.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status inválido. Use: {', '.join(valid_statuses)}")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Se mudou para aprovado/perdido, registrar responded_at
    if body.status in ("aprovado", "perdido") and "responded_at" not in updates:
        updates["responded_at"] = "now()"

    set_clause = ", ".join(
        f"{k} = {v}" if v == "now()" else f"{k} = :{k}"
        for k, v in updates.items()
    )
    params = {k: v for k, v in updates.items() if v != "now()"}
    params["id"] = str(quote_id)

    await db.execute(
        text(f"UPDATE quotes SET {set_clause}, updated_at = now() WHERE id = :id"),
        params,
    )
    full = await db.execute(text(f"{QUOTE_SELECT} WHERE q.id = :id"), {"id": str(quote_id)})
    row = full.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    return row_to_quote(row)


@router.get("/orcamentos/resumo/{client_id}", summary="Resumo de orçamentos por cliente")
async def resumo_orcamentos(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Retorna totais por status para o cliente — aprovado x perdido x pendente."""
    result = await db.execute(
        text("""
            SELECT
                status,
                count(*)        as total,
                sum(value)      as valor_total
            FROM quotes
            WHERE client_id = :client_id
            GROUP BY status
        """),
        {"client_id": str(client_id)},
    )
    return [dict(r._mapping) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Endpoints — Solicitação de diária
# ---------------------------------------------------------------------------

DAILY_SELECT = """
    SELECT
        dr.id::text,
        dr.requested_by::text,
        p1.full_name        as requested_by_name,
        dr.destination,
        dr.departure_date::text,
        dr.return_date::text,
        dr.purpose,
        dr.estimated_value,
        dr.status,
        dr.reviewed_by::text,
        p2.full_name        as reviewed_by_name,
        dr.reviewed_at::text,
        dr.review_notes,
        dr.approved_value,
        dr.created_at::text
    FROM daily_requests dr
    LEFT JOIN profiles p1 ON p1.id = dr.requested_by
    LEFT JOIN profiles p2 ON p2.id = dr.reviewed_by
"""


@router.get("/diarias", response_model=Page[DailyRequestResponse], summary="Listar solicitações de diária")
async def listar_diarias(
    status: str | None = Query(None, description="pendente, aprovada, recusada"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    # Comercial vê apenas as próprias solicitações
    if current_user.role == "comercial":
        conditions.append("dr.requested_by = :uid")
        params["uid"] = str(current_user.user_id)

    if status:
        conditions.append("dr.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM daily_requests dr WHERE {where}"), params
    )
    total = count.scalar()
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{DAILY_SELECT} WHERE {where} ORDER BY dr.created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_daily(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("/diarias", response_model=DailyRequestResponse, status_code=201, summary="Solicitar diária")
async def solicitar_diaria(
    body: DailyRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Comercial solicita diária ao financeiro."""
    result = await db.execute(
        text("""
            INSERT INTO daily_requests
                (requested_by, destination, departure_date, return_date, purpose, estimated_value)
            VALUES
                (:requested_by, :destination, :departure_date, :return_date, :purpose, :estimated_value)
            RETURNING id::text
        """),
        {**body.model_dump(), "requested_by": str(current_user.user_id)},
    )
    daily_id = result.fetchone().id
    full = await db.execute(text(f"{DAILY_SELECT} WHERE dr.id = :id"), {"id": daily_id})
    return row_to_daily(full.fetchone())


@router.patch("/diarias/{daily_id}/revisar", response_model=DailyRequestResponse, summary="Financeiro revisa diária")
async def revisar_diaria(
    daily_id: UUID,
    body: DailyRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Financeiro aprova ou recusa a solicitação de diária."""
    if current_user.role not in ("admin", "financeiro"):
        raise HTTPException(status_code=403, detail="Apenas financeiro pode revisar diárias")

    if not body.approved and not body.review_notes:
        raise HTTPException(status_code=400, detail="Justificativa obrigatória ao recusar")

    novo_status = "aprovada" if body.approved else "recusada"

    result = await db.execute(
        text("""
            UPDATE daily_requests SET
                status         = :status,
                reviewed_by    = :reviewed_by,
                reviewed_at    = now(),
                review_notes   = :review_notes,
                approved_value = :approved_value
            WHERE id = :id AND status = 'pendente'
            RETURNING id::text
        """),
        {
            "id": str(daily_id),
            "status": novo_status,
            "reviewed_by": str(current_user.user_id),
            "review_notes": body.review_notes,
            "approved_value": body.approved_value,
        },
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Solicitação não encontrada ou já revisada")

    full = await db.execute(text(f"{DAILY_SELECT} WHERE dr.id = :id"), {"id": str(daily_id)})
    return row_to_daily(full.fetchone())


# ---------------------------------------------------------------------------
# Endpoints — Entrega ao gerente (handover)
# ---------------------------------------------------------------------------

HANDOVER_SELECT = """
    SELECT
        h.id::text,
        h.client_id::text,
        cl.name         as client_name,
        h.from_profile::text,
        p1.full_name    as from_name,
        h.to_profile::text,
        p2.full_name    as to_name,
        h.contract_url,
        h.service_details,
        h.notes,
        h.status,
        h.rejection_reason,
        h.created_at::text,
        h.updated_at::text
    FROM client_handovers h
    JOIN clients cl      ON cl.id = h.client_id
    LEFT JOIN profiles p1 ON p1.id = h.from_profile
    LEFT JOIN profiles p2 ON p2.id = h.to_profile
"""


@router.get("/entregas", response_model=Page[HandoverResponse], summary="Listar entregas ao gerente")
async def listar_entregas(
    status: str | None = Query(None, description="pendente, aceito, devolvido"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    # Comercial vê apenas as próprias entregas
    if current_user.role == "comercial":
        conditions.append("h.from_profile = :uid")
        params["uid"] = str(current_user.user_id)
    # Gerente vê apenas as enviadas para ele
    elif current_user.role == "gerente":
        conditions.append("h.to_profile = :uid")
        params["uid"] = str(current_user.user_id)

    if status:
        conditions.append("h.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM client_handovers h WHERE {where}"), params
    )
    total = count.scalar()
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{HANDOVER_SELECT} WHERE {where} ORDER BY h.created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_handover(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("/entregas", response_model=HandoverResponse, status_code=201, summary="Entregar cliente ao gerente")
async def entregar_cliente(
    body: HandoverCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Comercial entrega o dossiê do cliente ao gerente técnico.
    Inclui contrato, detalhes dos serviços e observações.
    """
    if current_user.role not in ("admin", "comercial"):
        raise HTTPException(status_code=403, detail="Apenas comercial pode fazer entregas")

    # Verificar que o destinatário é gerente
    check = await db.execute(
        text("SELECT role FROM profiles WHERE id = :id"),
        {"id": body.to_profile},
    )
    row = check.fetchone()
    if not row or row.role not in ("gerente", "admin"):
        raise HTTPException(status_code=400, detail="Destinatário deve ser um gerente")

    result = await db.execute(
        text("""
            INSERT INTO client_handovers
                (client_id, from_profile, to_profile, contract_url, service_details, notes)
            VALUES
                (:client_id, :from_profile, :to_profile, :contract_url, :service_details, :notes)
            RETURNING id::text
        """),
        {**body.model_dump(), "from_profile": str(current_user.user_id)},
    )
    handover_id = result.fetchone().id
    full = await db.execute(text(f"{HANDOVER_SELECT} WHERE h.id = :id"), {"id": handover_id})
    return row_to_handover(full.fetchone())


@router.patch("/entregas/{handover_id}/revisar", response_model=HandoverResponse, summary="Gerente aceita ou devolve")
async def revisar_entrega(
    handover_id: UUID,
    body: HandoverReview,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Gerente aceita o dossiê ou devolve ao comercial com justificativa.
    """
    if current_user.role not in ("admin", "gerente"):
        raise HTTPException(status_code=403, detail="Apenas gerente pode revisar entregas")

    if not body.accepted and not body.rejection_reason:
        raise HTTPException(status_code=400, detail="Justificativa obrigatória ao devolver")

    novo_status = "aceito" if body.accepted else "devolvido"

    result = await db.execute(
        text("""
            UPDATE client_handovers SET
                status           = :status,
                rejection_reason = :rejection_reason,
                updated_at       = now()
            WHERE id = :id AND status = 'pendente'
            RETURNING id::text
        """),
        {
            "id": str(handover_id),
            "status": novo_status,
            "rejection_reason": body.rejection_reason,
        },
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Entrega não encontrada ou já revisada")

    full = await db.execute(text(f"{HANDOVER_SELECT} WHERE h.id = :id"), {"id": str(handover_id)})
    return row_to_handover(full.fetchone())
