from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user, require_gerente, require_admin, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/clientes", tags=["clientes"])


# ---------------------------------------------------------------------------
# Schemas — Cliente
# ---------------------------------------------------------------------------

class ClienteBase(BaseModel):
    name: str
    cnpj: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    contract_value: float | None = None
    contract_start: str | None = None   # date ISO string
    contract_end: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class ClienteCreate(ClienteBase):
    pass


class ClienteUpdate(BaseModel):
    name: str | None = None
    cnpj: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    contract_value: float | None = None
    contract_start: str | None = None
    contract_end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None


class ClienteResponse(BaseModel):
    id: str
    name: str
    cnpj: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    state: str | None
    contract_value: float | None
    contract_start: str | None
    contract_end: str | None
    latitude: float | None
    longitude: float | None
    is_active: bool
    created_by: str | None
    created_at: str
    updated_at: str
    # Contadores
    units_count: int = 0


# ---------------------------------------------------------------------------
# Schemas — Unidade do cliente
# ---------------------------------------------------------------------------

class UnidadeBase(BaseModel):
    name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class UnidadeCreate(UnidadeBase):
    pass


class UnidadeUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None


class UnidadeResponse(BaseModel):
    id: str
    client_id: str
    name: str
    address: str | None
    city: str | None
    state: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    latitude: float | None
    longitude: float | None
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_cliente(row) -> ClienteResponse:
    m = dict(row._mapping)
    return ClienteResponse(
        id=str(m["id"]),
        name=m["name"],
        cnpj=m.get("cnpj"),
        email=m.get("email"),
        phone=m.get("phone"),
        address=m.get("address"),
        city=m.get("city"),
        state=m.get("state"),
        contract_value=float(m["contract_value"]) if m.get("contract_value") else None,
        contract_start=str(m["contract_start"]) if m.get("contract_start") else None,
        contract_end=str(m["contract_end"]) if m.get("contract_end") else None,
        latitude=float(m["latitude"]) if m.get("latitude") else None,
        longitude=float(m["longitude"]) if m.get("longitude") else None,
        is_active=m["is_active"],
        created_by=str(m["created_by"]) if m.get("created_by") else None,
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
        units_count=m.get("units_count", 0),
    )


def row_to_unidade(row) -> UnidadeResponse:
    m = dict(row._mapping)
    return UnidadeResponse(
        id=str(m["id"]),
        client_id=str(m["client_id"]),
        name=m["name"],
        address=m.get("address"),
        city=m.get("city"),
        state=m.get("state"),
        contact_name=m.get("contact_name"),
        contact_email=m.get("contact_email"),
        contact_phone=m.get("contact_phone"),
        latitude=float(m["latitude"]) if m.get("latitude") else None,
        longitude=float(m["longitude"]) if m.get("longitude") else None,
        is_active=m["is_active"],
        created_at=str(m["created_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Clientes
# ---------------------------------------------------------------------------

@router.get("", response_model=Page[ClienteResponse], summary="Listar clientes")
async def listar_clientes(
    search: str | None = Query(None, description="Busca por nome, CNPJ ou cidade"),
    is_active: bool | None = Query(None, description="Filtrar por status"),
    state: str | None = Query(None, description="Filtrar por estado (UF)"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """
    Lista todos os clientes com paginação e filtros.
    Acessível por todos os módulos internos.
    """
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if search:
        conditions.append(
            "(unaccent(lower(c.name)) ilike unaccent(lower(:search)) "
            "OR c.cnpj ilike :search "
            "OR unaccent(lower(c.city)) ilike unaccent(lower(:search)))"
        )
        params["search"] = f"%{search}%"

    if is_active is not None:
        conditions.append("c.is_active = :is_active")
        params["is_active"] = is_active

    if state:
        conditions.append("upper(c.state) = upper(:state)")
        params["state"] = state

    where = " AND ".join(conditions)

    # Total
    count_result = await db.execute(
        text(f"SELECT count(*) FROM clients c WHERE {where}"),
        params,
    )
    total = count_result.scalar()

    # Dados com contagem de unidades
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"""
            SELECT
                c.id::text,
                c.name,
                c.cnpj,
                c.email,
                c.phone,
                c.address,
                c.city,
                c.state,
                c.contract_value,
                c.contract_start,
                c.contract_end,
                c.latitude,
                c.longitude,
                c.is_active,
                c.created_by::text,
                c.created_at,
                c.updated_at,
                (SELECT count(*) FROM client_units u WHERE u.client_id = c.id AND u.is_active = true) as units_count
            FROM clients c
            WHERE {where}
            ORDER BY c.name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [row_to_cliente(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("", response_model=ClienteResponse, status_code=201, summary="Criar cliente")
async def criar_cliente(
    body: ClienteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Cria um novo cliente. Acessível por comercial, gerente e admin.
    """
    result = await db.execute(
        text("""
            INSERT INTO clients (
                name, cnpj, email, phone, address, city, state,
                contract_value, contract_start, contract_end,
                latitude, longitude, created_by
            ) VALUES (
                :name, :cnpj, :email, :phone, :address, :city, :state,
                :contract_value, :contract_start, :contract_end,
                :latitude, :longitude, :created_by
            )
            RETURNING
                id::text, name, cnpj, email, phone, address, city, state,
                contract_value, contract_start, contract_end,
                latitude, longitude, is_active, created_by::text,
                created_at, updated_at
        """),
        {**body.model_dump(), "created_by": str(current_user.user_id)},
    )
    row = result.fetchone()
    cliente = row_to_cliente(row)
    cliente.units_count = 0
    return cliente


@router.get("/{cliente_id}", response_model=ClienteResponse, summary="Buscar cliente por ID")
async def buscar_cliente(
    cliente_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT
                c.id::text, c.name, c.cnpj, c.email, c.phone,
                c.address, c.city, c.state,
                c.contract_value, c.contract_start, c.contract_end,
                c.latitude, c.longitude, c.is_active,
                c.created_by::text, c.created_at, c.updated_at,
                (SELECT count(*) FROM client_units u WHERE u.client_id = c.id AND u.is_active = true) as units_count
            FROM clients c
            WHERE c.id = :id
        """),
        {"id": str(cliente_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return row_to_cliente(row)


@router.patch("/{cliente_id}", response_model=ClienteResponse, summary="Atualizar cliente")
async def atualizar_cliente(
    cliente_id: UUID,
    body: ClienteUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(cliente_id)

    result = await db.execute(
        text(f"""
            UPDATE clients
            SET {set_clause}, updated_at = now()
            WHERE id = :id
            RETURNING
                id::text, name, cnpj, email, phone, address, city, state,
                contract_value, contract_start, contract_end,
                latitude, longitude, is_active, created_by::text,
                created_at, updated_at
        """),
        updates,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return row_to_cliente(row)


@router.delete("/{cliente_id}", status_code=204, summary="Desativar cliente")
async def desativar_cliente(
    cliente_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Desativa o cliente (soft delete). Apenas gerente e admin.
    Clientes com O.S. em aberto não podem ser desativados.
    """
    # Verificar OS abertas
    os_result = await db.execute(
        text("""
            SELECT count(*) FROM service_orders
            WHERE client_id = :id
            AND status NOT IN ('encerrada', 'devolvida')
        """),
        {"id": str(cliente_id)},
    )
    if os_result.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cliente possui O.S. em aberto e não pode ser desativado",
        )

    result = await db.execute(
        text("UPDATE clients SET is_active = false, updated_at = now() WHERE id = :id RETURNING id"),
        {"id": str(cliente_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Cliente não encontrado")


# ---------------------------------------------------------------------------
# Endpoints — Unidades do cliente
# ---------------------------------------------------------------------------

@router.get("/{cliente_id}/unidades", response_model=list[UnidadeResponse], summary="Listar unidades")
async def listar_unidades(
    cliente_id: UUID,
    is_active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Lista todas as unidades/setores de um cliente."""
    conditions = ["client_id = :client_id"]
    params: dict[str, Any] = {"client_id": str(cliente_id)}

    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active

    where = " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT
                id::text, client_id::text, name, address, city, state,
                contact_name, contact_email, contact_phone,
                latitude, longitude, is_active, created_at
            FROM client_units
            WHERE {where}
            ORDER BY name
        """),
        params,
    )
    return [row_to_unidade(r) for r in result.fetchall()]


@router.post(
    "/{cliente_id}/unidades",
    response_model=UnidadeResponse,
    status_code=201,
    summary="Criar unidade",
)
async def criar_unidade(
    cliente_id: UUID,
    body: UnidadeCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Adiciona uma unidade/setor ao cliente."""
    # Verificar se cliente existe
    check = await db.execute(
        text("SELECT id FROM clients WHERE id = :id AND is_active = true"),
        {"id": str(cliente_id)},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="Cliente não encontrado ou inativo")

    result = await db.execute(
        text("""
            INSERT INTO client_units (
                client_id, name, address, city, state,
                contact_name, contact_email, contact_phone,
                latitude, longitude
            ) VALUES (
                :client_id, :name, :address, :city, :state,
                :contact_name, :contact_email, :contact_phone,
                :latitude, :longitude
            )
            RETURNING
                id::text, client_id::text, name, address, city, state,
                contact_name, contact_email, contact_phone,
                latitude, longitude, is_active, created_at
        """),
        {"client_id": str(cliente_id), **body.model_dump()},
    )
    return row_to_unidade(result.fetchone())


@router.get(
    "/{cliente_id}/unidades/{unidade_id}",
    response_model=UnidadeResponse,
    summary="Buscar unidade",
)
async def buscar_unidade(
    cliente_id: UUID,
    unidade_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            SELECT id::text, client_id::text, name, address, city, state,
                   contact_name, contact_email, contact_phone,
                   latitude, longitude, is_active, created_at
            FROM client_units
            WHERE id = :id AND client_id = :client_id
        """),
        {"id": str(unidade_id), "client_id": str(cliente_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")
    return row_to_unidade(row)


@router.patch(
    "/{cliente_id}/unidades/{unidade_id}",
    response_model=UnidadeResponse,
    summary="Atualizar unidade",
)
async def atualizar_unidade(
    cliente_id: UUID,
    unidade_id: UUID,
    body: UnidadeUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(unidade_id)
    updates["client_id"] = str(cliente_id)

    result = await db.execute(
        text(f"""
            UPDATE client_units
            SET {set_clause}
            WHERE id = :id AND client_id = :client_id
            RETURNING
                id::text, client_id::text, name, address, city, state,
                contact_name, contact_email, contact_phone,
                latitude, longitude, is_active, created_at
        """),
        updates,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")
    return row_to_unidade(row)


@router.delete("/{cliente_id}/unidades/{unidade_id}", status_code=204, summary="Desativar unidade")
async def desativar_unidade(
    cliente_id: UUID,
    unidade_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("""
            UPDATE client_units
            SET is_active = false
            WHERE id = :id AND client_id = :client_id
            RETURNING id
        """),
        {"id": str(unidade_id), "client_id": str(cliente_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Unidade não encontrada")


# ---------------------------------------------------------------------------
# Endpoint — Mapa de calor (para o módulo gerente)
# ---------------------------------------------------------------------------

@router.get("/mapa/calor", summary="Dados para mapa de calor de clientes")
async def mapa_calor(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """
    Retorna todos os clientes ativos com geolocalização e dados de OS
    para montar o mapa de calor no módulo gerente.
    """
    result = await db.execute(
        text("""
            SELECT
                c.id::text,
                c.name,
                c.city,
                c.state,
                c.latitude,
                c.longitude,
                c.contract_value,
                count(so.id) filter (where so.status = 'em_execucao') as os_em_aberto,
                count(so.id) filter (where so.status = 'encerrada') as os_concluidas,
                max(so.created_at) as ultima_os
            FROM clients c
            LEFT JOIN service_orders so ON so.client_id = c.id
            WHERE c.is_active = true
            AND c.latitude IS NOT NULL
            AND c.longitude IS NOT NULL
            GROUP BY c.id, c.name, c.city, c.state, c.latitude, c.longitude, c.contract_value
            ORDER BY c.name
        """),
    )
    rows = result.fetchall()
    return [
        {
            "id": r.id,
            "name": r.name,
            "city": r.city,
            "state": r.state,
            "latitude": float(r.latitude),
            "longitude": float(r.longitude),
            "contract_value": float(r.contract_value) if r.contract_value else None,
            "os_em_aberto": r.os_em_aberto,
            "os_concluidas": r.os_concluidas,
            "ultima_os": str(r.ultima_os) if r.ultima_os else None,
        }
        for r in rows
    ]
