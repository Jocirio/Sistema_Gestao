from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import get_current_user, require_gerente, require_admin, TokenData
from app.core.supabase import supabase_admin
from app.workers.tasks_email import send_magic_link_email

router = APIRouter(prefix="/portal", tags=["portal do cliente"])


# ---------------------------------------------------------------------------
# Autenticação do portal — separada do sistema interno
# Usa token próprio armazenado em portal_sessions
# ---------------------------------------------------------------------------

class MagicLinkRequest(BaseModel):
    email: EmailStr


class PortalTokenResponse(BaseModel):
    access_token: str
    portal_user_id: str
    client_id: str
    client_name: str
    expires_at: str


class PortalUserCreate(BaseModel):
    client_id: str
    name: str
    email: EmailStr


class PortalUserResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    name: str
    email: str
    is_active: bool
    last_login: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — O que o cliente vê
# ---------------------------------------------------------------------------

class PortalOSResponse(BaseModel):
    id: str
    os_number: str
    issued_at: str
    status: str
    sector_name: str | None
    collaborator_name: str
    collaborator_function: str | None
    services_description: str | None
    departure_date: str
    return_date: str
    days_away: int | None
    client_unit_name: str | None
    created_at: str


class PortalChecklistItem(BaseModel):
    title: str
    completed: bool
    completed_at: str | None


class PortalImplantacaoResponse(BaseModel):
    product_name: str
    plan_title: str
    total_items: int
    completed_items: int
    completion_pct: float
    checklist: list[PortalChecklistItem]


class PortalReportResponse(BaseModel):
    id: str
    os_number: str | None
    title: str
    collaborator_name: str
    client_unit_name: str | None
    status: str
    finalized_at: str | None
    pdf_url: str | None
    photos_count: int
    signatures_count: int
    created_at: str


class PortalContactResponse(BaseModel):
    name: str
    role: str
    email: str
    phone: str | None


class PortalNewRequestCreate(BaseModel):
    subject: str
    description: str
    urgency: str = "normal"   # baixa, normal, alta


class PortalConfigUpdate(BaseModel):
    show_os_status: bool | None = None
    show_implementation_checklist: bool | None = None
    show_service_reports: bool | None = None
    show_pdf_download: bool | None = None
    show_team_contacts: bool | None = None
    show_financial_data: bool | None = None
    allow_new_request: bool | None = None
    show_full_history: bool | None = None
    history_months: int | None = None


class PortalConfigResponse(BaseModel):
    client_id: str
    show_os_status: bool
    show_implementation_checklist: bool
    show_service_reports: bool
    show_pdf_download: bool
    show_team_contacts: bool
    show_financial_data: bool
    allow_new_request: bool
    show_full_history: bool
    history_months: int


# ---------------------------------------------------------------------------
# Dependency — extrair e validar sessão do portal
# ---------------------------------------------------------------------------

async def get_portal_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Valida o token de sessão do portal (Bearer no header Authorization).
    Retorna os dados da sessão: portal_user_id e client_id.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso do portal não fornecido",
        )
    token = auth.split(" ", 1)[1]

    result = await db.execute(
        text("""
            SELECT
                ps.id::text,
                ps.portal_user_id::text,
                pu.client_id::text,
                pu.name,
                pu.email,
                ps.expires_at
            FROM portal_sessions ps
            JOIN portal_users pu ON pu.id = ps.portal_user_id
            WHERE ps.token = :token AND pu.is_active = true
        """),
        {"token": token},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida ou expirada",
        )

    m = dict(row._mapping)
    if datetime.fromisoformat(str(m["expires_at"]).replace("+00:00", "+00:00")) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada — solicite um novo link de acesso",
        )

    return {
        "session_id": m["id"],
        "portal_user_id": m["portal_user_id"],
        "client_id": m["client_id"],
        "name": m["name"],
        "email": m["email"],
    }


async def get_portal_config(client_id: str, db: AsyncSession) -> dict:
    """Busca as configurações de visibilidade do portal para o cliente."""
    result = await db.execute(
        text("""
            SELECT * FROM portal_client_configs WHERE client_id = :client_id
        """),
        {"client_id": client_id},
    )
    row = result.fetchone()
    if not row:
        # Retorna configuração padrão se não existir
        return {
            "show_os_status": True,
            "show_implementation_checklist": True,
            "show_service_reports": True,
            "show_pdf_download": True,
            "show_team_contacts": True,
            "show_financial_data": False,
            "allow_new_request": False,
            "show_full_history": True,
            "history_months": 12,
        }
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# Endpoints — Gestão interna de usuários do portal (admin/gerente)
# ---------------------------------------------------------------------------

@router.get("/usuarios", response_model=list[PortalUserResponse], summary="Listar usuários do portal")
async def listar_usuarios_portal(
    client_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}
    if client_id:
        conditions.append("pu.client_id = :client_id")
        params["client_id"] = client_id

    result = await db.execute(
        text(f"""
            SELECT
                pu.id::text, pu.client_id::text, cl.name as client_name,
                pu.name, pu.email, pu.is_active,
                pu.last_login::text, pu.created_at::text
            FROM portal_users pu
            JOIN clients cl ON cl.id = pu.client_id
            WHERE {" AND ".join(conditions)}
            ORDER BY cl.name, pu.name
        """),
        params,
    )
    return [PortalUserResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/usuarios", response_model=PortalUserResponse, status_code=201, summary="Criar usuário do portal")
async def criar_usuario_portal(
    body: PortalUserCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Cria um usuário externo do portal do cliente.
    Após criar, enviar magic link via /portal/auth/enviar-link.
    """
    check = await db.execute(
        text("SELECT id FROM portal_users WHERE lower(email) = lower(:email)"),
        {"email": body.email},
    )
    if check.fetchone():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado no portal")

    result = await db.execute(
        text("""
            INSERT INTO portal_users (client_id, name, email)
            VALUES (:client_id, :name, :email)
            RETURNING id::text
        """),
        body.model_dump(),
    )
    user_id = result.fetchone().id

    full = await db.execute(
        text("""
            SELECT pu.id::text, pu.client_id::text, cl.name as client_name,
                   pu.name, pu.email, pu.is_active, pu.last_login::text, pu.created_at::text
            FROM portal_users pu
            JOIN clients cl ON cl.id = pu.client_id
            WHERE pu.id = :id
        """),
        {"id": user_id},
    )
    return PortalUserResponse(**dict(full.fetchone()._mapping))


@router.delete("/usuarios/{user_id}", status_code=204, summary="Desativar usuário do portal")
async def desativar_usuario_portal(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    result = await db.execute(
        text("UPDATE portal_users SET is_active = false WHERE id = :id RETURNING id"),
        {"id": str(user_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Usuário não encontrado")


# ---------------------------------------------------------------------------
# Endpoints — Autenticação do portal (magic link)
# ---------------------------------------------------------------------------

@router.post("/auth/enviar-link", summary="Enviar magic link ao cliente")
async def enviar_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Gera um magic link e envia por e-mail ao usuário do portal.
    O link expira em 15 minutos. Pode ser chamado pelo próprio usuário
    ou pelo sistema interno ao cadastrar um novo usuário.
    """
    result = await db.execute(
        text("SELECT id::text FROM portal_users WHERE lower(email) = lower(:email) AND is_active = true"),
        {"email": body.email},
    )
    row = result.fetchone()
    # Não revelar se o e-mail existe ou não (segurança)
    if not row:
        return {"message": "Se o e-mail estiver cadastrado, você receberá o link em instantes"}

    portal_user_id = row.id

    # Criar magic link (token gerado pelo banco)
    token_result = await db.execute(
        text("""
            INSERT INTO portal_magic_links (portal_user_id)
            VALUES (:portal_user_id)
            RETURNING token
        """),
        {"portal_user_id": portal_user_id},
    )
    token = token_result.fetchone().token

    # Disparar envio de e-mail via Celery
    send_magic_link_email.delay(portal_user_id, token, body.email)

    return {"message": "Se o e-mail estiver cadastrado, você receberá o link em instantes"}


@router.post("/auth/validar-link", response_model=PortalTokenResponse, summary="Validar magic link e iniciar sessão")
async def validar_magic_link(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Valida o magic link e retorna um token de sessão do portal.
    O magic link é de uso único e expira em 15 minutos.
    """
    result = await db.execute(
        text("""
            SELECT
                ml.id::text as link_id,
                ml.portal_user_id::text,
                ml.expires_at,
                ml.used_at,
                pu.client_id::text,
                cl.name as client_name,
                pu.email
            FROM portal_magic_links ml
            JOIN portal_users pu ON pu.id = ml.portal_user_id
            JOIN clients cl      ON cl.id = pu.client_id
            WHERE ml.token = :token
        """),
        {"token": token},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Link inválido")

    m = dict(row._mapping)

    if m.get("used_at"):
        raise HTTPException(status_code=401, detail="Link já utilizado — solicite um novo")

    if datetime.fromisoformat(str(m["expires_at"]).replace("+00:00", "+00:00")) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Link expirado — solicite um novo")

    # Marcar link como usado
    await db.execute(
        text("UPDATE portal_magic_links SET used_at = now() WHERE id = :id"),
        {"id": m["link_id"]},
    )

    # Criar sessão do portal (token de sessão gerado pelo banco)
    session_result = await db.execute(
        text("""
            INSERT INTO portal_sessions (portal_user_id)
            VALUES (:portal_user_id)
            RETURNING token, expires_at::text
        """),
        {"portal_user_id": m["portal_user_id"]},
    )
    session = dict(session_result.fetchone()._mapping)

    # Atualizar last_login do usuário
    await db.execute(
        text("UPDATE portal_users SET last_login = now() WHERE id = :id"),
        {"id": m["portal_user_id"]},
    )

    return PortalTokenResponse(
        access_token=session["token"],
        portal_user_id=m["portal_user_id"],
        client_id=m["client_id"],
        client_name=m["client_name"],
        expires_at=str(session["expires_at"]),
    )


# ---------------------------------------------------------------------------
# Endpoints — Área do cliente (autenticado via sessão do portal)
# ---------------------------------------------------------------------------

@router.get("/minha-conta", summary="Dados do cliente logado no portal")
async def minha_conta(
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """Retorna dados do cliente e configurações de visibilidade do portal."""
    result = await db.execute(
        text("""
            SELECT id::text, name, cnpj, email, phone, city, state,
                   contract_value, contract_start::text, contract_end::text
            FROM clients WHERE id = :id
        """),
        {"id": session["client_id"]},
    )
    client = dict(result.fetchone()._mapping)
    config = await get_portal_config(session["client_id"], db)

    # KPIs básicos
    os_result = await db.execute(
        text("""
            SELECT
                count(*) filter (where status NOT IN ('encerrada')) as em_aberto,
                count(*) filter (where status = 'encerrada')         as concluidas
            FROM service_orders WHERE client_id = :client_id
        """),
        {"client_id": session["client_id"]},
    )
    os_kpi = dict(os_result.fetchone()._mapping)

    impl_result = await db.execute(
        text("""
            SELECT coalesce(avg(completion_pct), 0) as media_implantacao
            FROM implementation_progress
            WHERE client_id = :client_id
        """),
        {"client_id": session["client_id"]},
    )
    impl_pct = float(impl_result.scalar() or 0)

    return {
        "usuario": {"name": session["name"], "email": session["email"]},
        "cliente": {**client, "contract_value": float(client["contract_value"]) if client.get("contract_value") else None},
        "kpis": {
            "os_em_aberto": int(os_kpi["em_aberto"]),
            "os_concluidas": int(os_kpi["concluidas"]),
            "media_implantacao_pct": round(impl_pct, 1),
        },
        "config": config,
    }


@router.get("/minhas-os", response_model=list[PortalOSResponse], summary="O.S. do cliente")
async def minhas_os(
    status: str | None = Query(None),
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """Lista as O.S. do cliente. Respeita configuração de visibilidade."""
    config = await get_portal_config(session["client_id"], db)
    if not config.get("show_os_status", True):
        raise HTTPException(status_code=403, detail="Funcionalidade não habilitada para este cliente")

    conditions = ["so.client_id = :client_id"]
    params: dict[str, Any] = {"client_id": session["client_id"]}

    if status:
        conditions.append("so.status = :status")
        params["status"] = status

    if not config.get("show_full_history", True):
        months = config.get("history_months", 12)
        conditions.append(f"so.created_at >= current_date - interval '{months} months'")

    result = await db.execute(
        text(f"""
            SELECT
                so.id::text,
                so.os_number,
                so.issued_at::text,
                so.status,
                sec.name            as sector_name,
                p.full_name         as collaborator_name,
                jf.name             as collaborator_function,
                so.services_description,
                so.departure_date::text,
                so.return_date::text,
                so.days_away,
                cu.name             as client_unit_name,
                so.created_at::text
            FROM service_orders so
            LEFT JOIN os_sectors sec   ON sec.id = so.sector_id
            LEFT JOIN profiles p       ON p.id   = so.collaborator_id
            LEFT JOIN job_functions jf ON jf.id  = p.job_function_id
            LEFT JOIN client_units cu  ON cu.id  = so.client_unit_id
            WHERE {" AND ".join(conditions)}
            ORDER BY so.created_at DESC
        """),
        params,
    )
    return [
        PortalOSResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "issued_at": str(dict(r._mapping)["issued_at"]),
            "departure_date": str(dict(r._mapping)["departure_date"]),
            "return_date": str(dict(r._mapping)["return_date"]),
            "created_at": str(dict(r._mapping)["created_at"]),
        })
        for r in result.fetchall()
    ]


@router.get("/implantacao", response_model=list[PortalImplantacaoResponse], summary="Progresso de implantação")
async def implantacao(
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """Progresso de implantação por produto. Inclui checklist detalhado."""
    config = await get_portal_config(session["client_id"], db)
    if not config.get("show_implementation_checklist", True):
        raise HTTPException(status_code=403, detail="Funcionalidade não habilitada para este cliente")

    # Buscar planos e itens
    result = await db.execute(
        text("""
            SELECT
                pr.name                 as product_name,
                ip.title                as plan_title,
                ip.id                   as plan_id,
                coalesce(ip_total.total_items, 0)     as total_items,
                coalesce(ip_total.completed_items, 0) as completed_items,
                coalesce(ip_total.completion_pct, 0)  as completion_pct
            FROM client_products cp
            JOIN products pr ON pr.id = cp.product_id
            LEFT JOIN implementation_plans ip ON ip.client_product_id = cp.id
            LEFT JOIN (
                SELECT plan_id,
                       count(*) as total_items,
                       count(*) filter (where completed) as completed_items,
                       case when count(*) = 0 then 0
                       else round(count(*) filter (where completed)::numeric / count(*) * 100, 1)
                       end as completion_pct
                FROM implementation_checklist_items
                GROUP BY plan_id
            ) ip_total ON ip_total.plan_id = ip.id
            WHERE cp.client_id = :client_id
            ORDER BY pr.name
        """),
        {"client_id": session["client_id"]},
    )
    planos = result.fetchall()

    response = []
    for p in planos:
        pm = dict(p._mapping)
        # Buscar itens do checklist
        items_result = await db.execute(
            text("""
                SELECT title, completed, completed_at::text
                FROM implementation_checklist_items
                WHERE plan_id = :plan_id
                ORDER BY order_index, created_at
            """),
            {"plan_id": pm["plan_id"]},
        )
        checklist = [
            PortalChecklistItem(
                title=i.title,
                completed=i.completed,
                completed_at=str(i.completed_at) if i.completed_at else None,
            )
            for i in items_result.fetchall()
        ]
        response.append(PortalImplantacaoResponse(
            product_name=pm["product_name"],
            plan_title=pm["plan_title"] or "",
            total_items=int(pm["total_items"]),
            completed_items=int(pm["completed_items"]),
            completion_pct=float(pm["completion_pct"]),
            checklist=checklist,
        ))
    return response


@router.get("/meus-relatorios", response_model=list[PortalReportResponse], summary="Relatórios de atendimento")
async def meus_relatorios(
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """Relatórios de atendimento finalizados visíveis ao cliente."""
    config = await get_portal_config(session["client_id"], db)
    if not config.get("show_service_reports", True):
        raise HTTPException(status_code=403, detail="Funcionalidade não habilitada para este cliente")

    show_pdf = config.get("show_pdf_download", True)

    result = await db.execute(
        text("""
            SELECT
                sr.id::text,
                so.os_number,
                sr.title,
                p.full_name         as collaborator_name,
                cu.name             as client_unit_name,
                sr.status,
                sr.finalized_at::text,
                CASE WHEN :show_pdf THEN sr.pdf_url ELSE null END as pdf_url,
                (SELECT count(*) FROM report_photos rp WHERE rp.report_id = sr.id)     as photos_count,
                (SELECT count(*) FROM report_signatures rs WHERE rs.report_id = sr.id) as signatures_count,
                sr.created_at::text
            FROM service_reports sr
            LEFT JOIN service_orders so ON so.id = sr.service_order_id
            LEFT JOIN profiles p        ON p.id  = sr.collaborator_id
            LEFT JOIN client_units cu   ON cu.id = sr.client_unit_id
            WHERE sr.client_id = :client_id AND sr.status = 'finalizado'
            ORDER BY sr.finalized_at DESC
        """),
        {"client_id": session["client_id"], "show_pdf": show_pdf},
    )
    return [
        PortalReportResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "photos_count": int(dict(r._mapping)["photos_count"]),
            "signatures_count": int(dict(r._mapping)["signatures_count"]),
        })
        for r in result.fetchall()
    ]


@router.get("/contatos", response_model=list[PortalContactResponse], summary="Contatos da equipe responsável")
async def contatos(
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """Retorna os contatos internos vinculados ao cliente."""
    config = await get_portal_config(session["client_id"], db)
    if not config.get("show_team_contacts", True):
        raise HTTPException(status_code=403, detail="Funcionalidade não habilitada para este cliente")

    result = await db.execute(
        text("""
            SELECT DISTINCT
                p.full_name     as name,
                p.role,
                au.email,
                p.phone
            FROM service_orders so
            JOIN profiles p     ON p.id  = so.collaborator_id
            JOIN auth.users au  ON au.id = p.id
            WHERE so.client_id = :client_id
            AND so.created_at >= current_date - interval '12 months'
            UNION
            SELECT DISTINCT
                p.full_name, p.role, au.email, p.phone
            FROM client_handovers ch
            JOIN profiles p    ON p.id  = ch.from_profile
            JOIN auth.users au ON au.id = p.id
            WHERE ch.client_id = :client_id
            ORDER BY role, name
        """),
        {"client_id": session["client_id"]},
    )
    return [PortalContactResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/solicitar-atendimento", summary="Cliente solicita novo atendimento")
async def solicitar_atendimento(
    body: PortalNewRequestCreate,
    session: dict = Depends(get_portal_session),
    db: AsyncSession = Depends(get_db),
):
    """
    Permite ao cliente solicitar um novo atendimento pelo portal.
    Só disponível se allow_new_request estiver habilitado nas configurações.
    Cria uma atividade no módulo comercial para acompanhamento.
    """
    config = await get_portal_config(session["client_id"], db)
    if not config.get("allow_new_request", False):
        raise HTTPException(status_code=403, detail="Solicitação de atendimento não habilitada para este cliente")

    valid_urgency = {"baixa", "normal", "alta"}
    if body.urgency not in valid_urgency:
        raise HTTPException(status_code=400, detail=f"Urgência deve ser: {', '.join(valid_urgency)}")

    # Criar atividade no histórico do cliente
    await db.execute(
        text("""
            INSERT INTO client_activities (client_id, type, title, description)
            VALUES (
                :client_id,
                'outro',
                :title,
                :description
            )
        """),
        {
            "client_id": session["client_id"],
            "title": f"[PORTAL] {body.subject} — Urgência: {body.urgency}",
            "description": body.description,
        },
    )

    return {
        "message": "Solicitação registrada com sucesso. Nossa equipe entrará em contato em breve.",
        "subject": body.subject,
        "urgency": body.urgency,
    }


# ---------------------------------------------------------------------------
# Endpoints — Configurações do portal por cliente (admin/gerente)
# ---------------------------------------------------------------------------

@router.get("/config/{client_id}", response_model=PortalConfigResponse, summary="Configurações do portal para o cliente")
async def buscar_config_portal(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    config = await get_portal_config(str(client_id), db)
    return PortalConfigResponse(client_id=str(client_id), **{k: v for k, v in config.items() if k != "client_id"})


@router.put("/config/{client_id}", response_model=PortalConfigResponse, summary="Atualizar configurações do portal")
async def atualizar_config_portal(
    client_id: UUID,
    body: PortalConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_gerente),
):
    """
    Habilita ou desabilita funcionalidades do portal por cliente.
    Usa UPSERT — cria as configurações se não existirem.
    """
    current = await get_portal_config(str(client_id), db)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    merged = {**current, **updates}

    await db.execute(
        text("""
            INSERT INTO portal_client_configs (
                client_id,
                show_os_status, show_implementation_checklist, show_service_reports,
                show_pdf_download, show_team_contacts, show_financial_data,
                allow_new_request, show_full_history, history_months
            ) VALUES (
                :client_id,
                :show_os_status, :show_implementation_checklist, :show_service_reports,
                :show_pdf_download, :show_team_contacts, :show_financial_data,
                :allow_new_request, :show_full_history, :history_months
            )
            ON CONFLICT (client_id) DO UPDATE SET
                show_os_status                = EXCLUDED.show_os_status,
                show_implementation_checklist = EXCLUDED.show_implementation_checklist,
                show_service_reports          = EXCLUDED.show_service_reports,
                show_pdf_download             = EXCLUDED.show_pdf_download,
                show_team_contacts            = EXCLUDED.show_team_contacts,
                show_financial_data           = EXCLUDED.show_financial_data,
                allow_new_request             = EXCLUDED.allow_new_request,
                show_full_history             = EXCLUDED.show_full_history,
                history_months                = EXCLUDED.history_months,
                updated_at                    = now()
        """),
        {"client_id": str(client_id), **merged},
    )

    return PortalConfigResponse(client_id=str(client_id), **merged)
