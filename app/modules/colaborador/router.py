from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID

from app.core.database import get_db
from app.core.security import (
    get_current_user,
    require_admin,
    require_gerente,
    TokenData,
)
from app.core.supabase import supabase_admin
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/colaboradores", tags=["colaboradores"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ColaboradorResponse(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    phone: str | None
    avatar_url: str | None
    is_active: bool
    os_blocked: bool
    blocked_reason: str | None
    job_function_id: str | None
    job_function_name: str | None
    daily_rate: float | None


class ColaboradorCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: str = "colaborador"
    phone: str | None = None
    job_function_id: str | None = None


class ColaboradorUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role: str | None = None
    job_function_id: str | None = None
    is_active: bool | None = None


class VacationRequest(BaseModel):
    start_date: str   # ISO date
    end_date: str     # ISO date


class VacationResponse(BaseModel):
    id: str
    collaborator_id: str
    collaborator_name: str
    start_date: str
    end_date: str
    days_count: int
    status: str
    reviewed_by: str | None
    reviewed_at: str | None
    rejection_reason: str | None
    financial_impact: float | None
    created_at: str


class VacationReview(BaseModel):
    approved: bool
    rejection_reason: str | None = None
    financial_impact: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_colaborador(row) -> ColaboradorResponse:
    m = dict(row._mapping)
    return ColaboradorResponse(
        id=str(m["id"]),
        full_name=m["full_name"],
        email=m.get("email", ""),
        role=m["role"],
        phone=m.get("phone"),
        avatar_url=m.get("avatar_url"),
        is_active=m["is_active"],
        os_blocked=m["os_blocked"],
        blocked_reason=m.get("blocked_reason"),
        job_function_id=str(m["job_function_id"]) if m.get("job_function_id") else None,
        job_function_name=m.get("job_function_name"),
        daily_rate=float(m["daily_rate"]) if m.get("daily_rate") else None,
    )


def row_to_vacation(row) -> VacationResponse:
    m = dict(row._mapping)
    return VacationResponse(
        id=str(m["id"]),
        collaborator_id=str(m["collaborator_id"]),
        collaborator_name=m["collaborator_name"],
        start_date=str(m["start_date"]),
        end_date=str(m["end_date"]),
        days_count=m["days_count"],
        status=m["status"],
        reviewed_by=str(m["reviewed_by"]) if m.get("reviewed_by") else None,
        reviewed_at=str(m["reviewed_at"]) if m.get("reviewed_at") else None,
        rejection_reason=m.get("rejection_reason"),
        financial_impact=float(m["financial_impact"]) if m.get("financial_impact") else None,
        created_at=str(m["created_at"]),
    )


COLABORADOR_SELECT = """
    SELECT
        p.id::text,
        p.full_name,
        au.email,
        p.role,
        p.phone,
        p.avatar_url,
        p.is_active,
        p.os_blocked,
        p.blocked_reason,
        p.job_function_id::text,
        jf.name  as job_function_name,
        jf.daily_rate
    FROM profiles p
    JOIN auth.users au ON au.id = p.id
    LEFT JOIN job_functions jf ON jf.id = p.job_function_id
"""


# ---------------------------------------------------------------------------
# Endpoints — Colaboradores
# ---------------------------------------------------------------------------

@router.get("", response_model=Page[ColaboradorResponse], summary="Listar colaboradores")
async def listar_colaboradores(
    search: str | None = Query(None, description="Busca por nome ou e-mail"),
    role: str | None = Query(None, description="Filtrar por perfil"),
    is_active: bool | None = Query(None),
    os_blocked: bool | None = Query(None, description="Filtrar bloqueados por adiantamento"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if search:
        conditions.append(
            "(unaccent(lower(p.full_name)) ilike unaccent(lower(:search)) "
            "OR lower(au.email) ilike lower(:search))"
        )
        params["search"] = f"%{search}%"

    if role:
        conditions.append("p.role = :role")
        params["role"] = role

    if is_active is not None:
        conditions.append("p.is_active = :is_active")
        params["is_active"] = is_active

    if os_blocked is not None:
        conditions.append("p.os_blocked = :os_blocked")
        params["os_blocked"] = os_blocked

    where = " AND ".join(conditions)

    count_result = await db.execute(
        text(f"""
            SELECT count(*) FROM profiles p
            JOIN auth.users au ON au.id = p.id
            WHERE {where}
        """),
        params,
    )
    total = count_result.scalar()

    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"""
            {COLABORADOR_SELECT}
            WHERE {where}
            ORDER BY p.full_name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [row_to_colaborador(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("", response_model=ColaboradorResponse, status_code=201, summary="Criar colaborador")
async def criar_colaborador(
    body: ColaboradorCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    Cria um novo usuário no Supabase Auth e o perfil correspondente.
    Apenas administradores podem criar usuários.
    """
    # Criar usuário no Supabase Auth
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email": body.email,
            "password": body.password,
            "email_confirm": True,
            "user_metadata": {"full_name": body.full_name},
        })
        user_id = auth_response.user.id
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar usuário: {str(e)}",
        )

    # Atualizar perfil criado automaticamente pelo trigger
    await db.execute(
        text("""
            UPDATE profiles
            SET
                full_name = :full_name,
                role = :role,
                phone = :phone,
                job_function_id = :job_function_id,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "id": str(user_id),
            "full_name": body.full_name,
            "role": body.role,
            "phone": body.phone,
            "job_function_id": body.job_function_id,
        },
    )

    result = await db.execute(
        text(f"{COLABORADOR_SELECT} WHERE p.id = :id"),
        {"id": str(user_id)},
    )
    return row_to_colaborador(result.fetchone())


@router.get("/bloqueados", response_model=list[ColaboradorResponse], summary="Colaboradores bloqueados")
async def listar_bloqueados(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """Lista colaboradores com bloqueio ativo por adiantamento pendente."""
    result = await db.execute(
        text(f"{COLABORADOR_SELECT} WHERE p.os_blocked = true ORDER BY p.full_name"),
    )
    return [row_to_colaborador(r) for r in result.fetchall()]


@router.get("/{colaborador_id}", response_model=ColaboradorResponse, summary="Buscar colaborador")
async def buscar_colaborador(
    colaborador_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # Colaborador só pode ver o próprio perfil
    if current_user.role == "colaborador" and current_user.user_id != colaborador_id:
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    result = await db.execute(
        text(f"{COLABORADOR_SELECT} WHERE p.id = :id"),
        {"id": str(colaborador_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    return row_to_colaborador(row)


@router.patch("/{colaborador_id}", response_model=ColaboradorResponse, summary="Atualizar colaborador")
async def atualizar_colaborador(
    colaborador_id: UUID,
    body: ColaboradorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # Colaborador só pode editar o próprio perfil e não pode mudar role
    if current_user.role == "colaborador":
        if current_user.user_id != colaborador_id:
            raise HTTPException(status_code=403, detail="Acesso não permitido")
        if body.role or body.is_active is not None:
            raise HTTPException(status_code=403, detail="Você não pode alterar role ou status")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(colaborador_id)

    await db.execute(
        text(f"UPDATE profiles SET {set_clause}, updated_at = now() WHERE id = :id"),
        updates,
    )

    result = await db.execute(
        text(f"{COLABORADOR_SELECT} WHERE p.id = :id"),
        {"id": str(colaborador_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    return row_to_colaborador(row)


# ---------------------------------------------------------------------------
# Endpoints — Férias
# ---------------------------------------------------------------------------

@router.post(
    "/{colaborador_id}/ferias",
    response_model=VacationResponse,
    status_code=201,
    summary="Solicitar férias",
)
async def solicitar_ferias(
    colaborador_id: UUID,
    body: VacationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Colaborador solicita férias. Apenas o próprio colaborador pode solicitar,
    ou um admin/gerente pode solicitar por ele.
    """
    if current_user.role == "colaborador" and current_user.user_id != colaborador_id:
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    result = await db.execute(
        text("""
            INSERT INTO vacation_requests (collaborator_id, start_date, end_date)
            VALUES (:collaborator_id, :start_date, :end_date)
            RETURNING
                id::text, collaborator_id::text,
                start_date, end_date, days_count, status,
                reviewed_by::text, reviewed_at, rejection_reason,
                financial_impact, created_at
        """),
        {
            "collaborator_id": str(colaborador_id),
            "start_date": body.start_date,
            "end_date": body.end_date,
        },
    )
    row = result.fetchone()

    # Buscar nome do colaborador
    name_result = await db.execute(
        text("SELECT full_name FROM profiles WHERE id = :id"),
        {"id": str(colaborador_id)},
    )
    name_row = name_result.fetchone()
    collaborator_name = name_row.full_name if name_row else ""

    m = dict(row._mapping)
    m["collaborator_name"] = collaborator_name
    return row_to_vacation(type("Row", (), {"_mapping": m})())


@router.get(
    "/ferias/pendentes",
    response_model=list[VacationResponse],
    summary="Solicitações de férias pendentes",
)
async def ferias_pendentes(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """Lista todas as solicitações de férias aguardando aprovação do gerente."""
    result = await db.execute(
        text("""
            SELECT
                vr.id::text,
                vr.collaborator_id::text,
                p.full_name as collaborator_name,
                vr.start_date,
                vr.end_date,
                vr.days_count,
                vr.status,
                vr.reviewed_by::text,
                vr.reviewed_at,
                vr.rejection_reason,
                vr.financial_impact,
                vr.created_at
            FROM vacation_requests vr
            JOIN profiles p ON p.id = vr.collaborator_id
            WHERE vr.status = 'solicitada'
            ORDER BY vr.start_date
        """),
    )
    return [row_to_vacation(r) for r in result.fetchall()]


@router.get(
    "/{colaborador_id}/ferias",
    response_model=list[VacationResponse],
    summary="Férias do colaborador",
)
async def ferias_colaborador(
    colaborador_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.role == "colaborador" and current_user.user_id != colaborador_id:
        raise HTTPException(status_code=403, detail="Acesso não permitido")

    result = await db.execute(
        text("""
            SELECT
                vr.id::text,
                vr.collaborator_id::text,
                p.full_name as collaborator_name,
                vr.start_date,
                vr.end_date,
                vr.days_count,
                vr.status,
                vr.reviewed_by::text,
                vr.reviewed_at,
                vr.rejection_reason,
                vr.financial_impact,
                vr.created_at
            FROM vacation_requests vr
            JOIN profiles p ON p.id = vr.collaborator_id
            WHERE vr.collaborator_id = :id
            ORDER BY vr.start_date DESC
        """),
        {"id": str(colaborador_id)},
    )
    return [row_to_vacation(r) for r in result.fetchall()]


@router.patch(
    "/ferias/{ferias_id}/revisar",
    response_model=VacationResponse,
    summary="Aprovar ou recusar férias",
)
async def revisar_ferias(
    ferias_id: UUID,
    body: VacationReview,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_gerente),
):
    """Gerente aprova ou recusa a solicitação de férias."""
    novo_status = "aprovada" if body.approved else "recusada"

    result = await db.execute(
        text("""
            UPDATE vacation_requests
            SET
                status           = :status,
                reviewed_by      = :reviewed_by,
                reviewed_at      = now(),
                rejection_reason = :rejection_reason,
                financial_impact = :financial_impact,
                updated_at       = now()
            WHERE id = :id AND status = 'solicitada'
            RETURNING
                id::text, collaborator_id::text,
                start_date, end_date, days_count, status,
                reviewed_by::text, reviewed_at, rejection_reason,
                financial_impact, created_at
        """),
        {
            "id": str(ferias_id),
            "status": novo_status,
            "reviewed_by": str(current_user.user_id),
            "rejection_reason": body.rejection_reason,
            "financial_impact": body.financial_impact,
        },
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Solicitação não encontrada ou já revisada",
        )

    name_result = await db.execute(
        text("SELECT full_name FROM profiles WHERE id = :id"),
        {"id": str(dict(row._mapping)["collaborator_id"])},
    )
    name_row = name_result.fetchone()
    m = dict(row._mapping)
    m["collaborator_name"] = name_row.full_name if name_row else ""
    return row_to_vacation(type("Row", (), {"_mapping": m})())
