from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.supabase import supabase_admin

# Esquema Bearer para extrair o token do header Authorization
bearer_scheme = HTTPBearer()


# ---------------------------------------------------------------------------
# Schemas de token
# ---------------------------------------------------------------------------

class TokenData(BaseModel):
    user_id: UUID
    email: str
    role: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Criação de tokens JWT
# ---------------------------------------------------------------------------

def create_access_token(data: dict[str, Any]) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload.update({"exp": expire, "type": "access"})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload.update({"exp": expire, "type": "refresh"})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_token_pair(user_id: str, email: str, role: str) -> TokenPair:
    data = {"sub": user_id, "email": email, "role": role}
    return TokenPair(
        access_token=create_access_token(data),
        refresh_token=create_refresh_token(data),
    )


# ---------------------------------------------------------------------------
# Verificação de token
# ---------------------------------------------------------------------------

def verify_token(token: str, expected_type: str = "access") -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != expected_type:
            raise credentials_exception

        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        role: str = payload.get("role", "colaborador")

        if not user_id or not email:
            raise credentials_exception

        return TokenData(user_id=UUID(user_id), email=email, role=role)

    except JWTError:
        raise credentials_exception


# ---------------------------------------------------------------------------
# Dependencies para injeção nas rotas
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenData:
    """Valida o token e retorna os dados do usuário atual."""
    return verify_token(credentials.credentials, expected_type="access")


async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")
    return current_user


async def require_financeiro(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role not in ("admin", "financeiro"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito ao módulo financeiro")
    return current_user


async def require_gerente(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role not in ("admin", "gerente"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito ao módulo gerente")
    return current_user


async def require_comercial(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role not in ("admin", "comercial"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito ao módulo comercial")
    return current_user


async def require_any_internal(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Qualquer usuário interno autenticado."""
    return current_user


# ---------------------------------------------------------------------------
# Autenticação via Supabase Auth (login com e-mail + senha)
# ---------------------------------------------------------------------------

async def authenticate_user(email: str, password: str) -> dict:
    """
    Autentica usando o Supabase Auth.
    Retorna os dados da sessão do Supabase incluindo o user_id.
    """
    try:
        response = supabase_admin.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        return {
            "user_id": response.user.id,
            "email": response.user.email,
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )
