from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    TokenPair,
    TokenData,
    authenticate_user,
    create_token_pair,
    verify_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["autenticação"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileResponse(BaseModel):
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenPair, summary="Login com e-mail e senha")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    """
    Autentica o usuário via Supabase Auth e retorna o par de tokens JWT.
    O access_token expira em 60 minutos. Use o refresh_token para renovar.
    """
    auth_data = await authenticate_user(body.email, body.password)

    # Busca o perfil para obter o role
    result = await db.execute(
        text("SELECT role, is_active FROM profiles WHERE id = :uid"),
        {"uid": auth_data["user_id"]},
    )
    profile = result.fetchone()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil não encontrado. Contate o administrador.",
        )

    if not profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo. Contate o administrador.",
        )

    return create_token_pair(
        user_id=str(auth_data["user_id"]),
        email=auth_data["email"],
        role=profile.role,
    )


@router.post("/refresh", response_model=TokenPair, summary="Renovar access token")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    """Usa o refresh_token para gerar um novo par de tokens."""
    token_data = verify_token(body.refresh_token, expected_type="refresh")

    # Verifica se o usuário ainda está ativo
    result = await db.execute(
        text("SELECT role, is_active FROM profiles WHERE id = :uid"),
        {"uid": str(token_data.user_id)},
    )
    profile = result.fetchone()

    if not profile or not profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário inativo ou não encontrado",
        )

    return create_token_pair(
        user_id=str(token_data.user_id),
        email=token_data.email,
        role=profile.role,
    )


@router.get("/me", response_model=ProfileResponse, summary="Perfil do usuário logado")
async def me(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Retorna os dados do perfil do usuário autenticado."""
    result = await db.execute(
        text("""
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
                p.job_function_id::text
            FROM profiles p
            JOIN auth.users au ON au.id = p.id
            WHERE p.id = :uid
        """),
        {"uid": str(current_user.user_id)},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil não encontrado")

    return ProfileResponse(
        id=row.id,
        full_name=row.full_name,
        email=row.email,
        role=row.role,
        phone=row.phone,
        avatar_url=row.avatar_url,
        is_active=row.is_active,
        os_blocked=row.os_blocked,
        blocked_reason=row.blocked_reason,
        job_function_id=row.job_function_id,
    )
