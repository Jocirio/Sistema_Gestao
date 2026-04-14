from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.core.database import get_db
from app.core.security import get_current_user, require_admin, TokenData
from app.core.storage import upload_logo
from app.core.config import settings

router = APIRouter(prefix="/config", tags=["configurações"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CompanySettingsResponse(BaseModel):
    id: str
    razao_social: str
    cnpj: str | None
    endereco: str | None
    email_contato: str | None
    telefone: str | None
    logo_url: str | None
    os_exercise_year: int
    os_sequence_start: int
    os_current_sequence: int
    advance_max_days: int
    advance_max_os: int


class CompanySettingsUpdate(BaseModel):
    razao_social: str | None = None
    cnpj: str | None = None
    endereco: str | None = None
    email_contato: str | None = None
    telefone: str | None = None
    os_exercise_year: int | None = None
    os_sequence_start: int | None = None
    advance_max_days: int | None = None
    advance_max_os: int | None = None


class FeatureToggle(BaseModel):
    module: str
    feature_key: str
    label: str
    enabled: bool


class FeatureToggleUpdate(BaseModel):
    enabled: bool


class JobFunction(BaseModel):
    id: str
    name: str
    description: str | None
    daily_rate: float
    is_active: bool


class JobFunctionCreate(BaseModel):
    name: str
    description: str | None = None
    daily_rate: float


class OsSector(BaseModel):
    id: str
    name: str
    is_active: bool


class OsSectorCreate(BaseModel):
    name: str


class AdvanceType(BaseModel):
    id: str
    name: str
    max_value: float | None
    is_active: bool


class AdvanceTypeCreate(BaseModel):
    name: str
    max_value: float | None = None


# ---------------------------------------------------------------------------
# Endpoints — Configurações da empresa
# ---------------------------------------------------------------------------

@router.get("/company", response_model=CompanySettingsResponse)
async def get_company_settings(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(text("SELECT * FROM company_settings LIMIT 1"))
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Configurações não encontradas")
    return CompanySettingsResponse(**dict(row._mapping))


@router.patch("/company", response_model=CompanySettingsResponse)
async def update_company_settings(
    body: CompanySettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["updated_at"] = "now()"

    await db.execute(
        text(f"UPDATE company_settings SET {set_clause}, updated_at = now()"),
        updates,
    )
    result = await db.execute(text("SELECT * FROM company_settings LIMIT 1"))
    return CompanySettingsResponse(**dict(result.fetchone()._mapping))


@router.post("/company/logo", summary="Upload da logo da empresa")
async def upload_company_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    Faz upload da logo. Aceita PNG, JPG ou WebP.
    A logo aparecerá no cabeçalho de todas as O.S. e relatórios exportados.
    """
    logo_url = await upload_logo(file)
    await db.execute(
        text("UPDATE company_settings SET logo_url = :url, updated_at = now()"),
        {"url": logo_url},
    )
    return {"logo_url": logo_url}


# ---------------------------------------------------------------------------
# Endpoints — Feature toggles
# ---------------------------------------------------------------------------

@router.get("/features", response_model=list[FeatureToggle])
async def list_feature_toggles(
    module: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    query = "SELECT module, feature_key, label, enabled FROM feature_toggles"
    params: dict[str, Any] = {}
    if module:
        query += " WHERE module = :module"
        params["module"] = module
    query += " ORDER BY module, label"
    result = await db.execute(text(query), params)
    return [FeatureToggle(**dict(r._mapping)) for r in result.fetchall()]


@router.patch("/features/{module}/{feature_key}", response_model=FeatureToggle)
async def update_feature_toggle(
    module: str,
    feature_key: str,
    body: FeatureToggleUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    result = await db.execute(
        text("""
            UPDATE feature_toggles
            SET enabled = :enabled, updated_at = now()
            WHERE module = :module AND feature_key = :key
            RETURNING module, feature_key, label, enabled
        """),
        {"enabled": body.enabled, "module": module, "key": feature_key},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Toggle não encontrado")
    return FeatureToggle(**dict(row._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Funções de colaboradores
# ---------------------------------------------------------------------------

@router.get("/job-functions", response_model=list[JobFunction])
async def list_job_functions(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id::text, name, description, daily_rate, is_active FROM job_functions ORDER BY name")
    )
    return [JobFunction(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/job-functions", response_model=JobFunction, status_code=201)
async def create_job_function(
    body: JobFunctionCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    result = await db.execute(
        text("""
            INSERT INTO job_functions (name, description, daily_rate)
            VALUES (:name, :description, :daily_rate)
            RETURNING id::text, name, description, daily_rate, is_active
        """),
        body.model_dump(),
    )
    return JobFunction(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Setores de OS
# ---------------------------------------------------------------------------

@router.get("/os-sectors", response_model=list[OsSector])
async def list_os_sectors(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id::text, name, is_active FROM os_sectors ORDER BY name")
    )
    return [OsSector(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/os-sectors", response_model=OsSector, status_code=201)
async def create_os_sector(
    body: OsSectorCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    result = await db.execute(
        text("INSERT INTO os_sectors (name) VALUES (:name) RETURNING id::text, name, is_active"),
        {"name": body.name},
    )
    return OsSector(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Tipos de adiantamento
# ---------------------------------------------------------------------------

@router.get("/advance-types", response_model=list[AdvanceType])
async def list_advance_types(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id::text, name, max_value, is_active FROM advance_types ORDER BY name")
    )
    return [AdvanceType(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/advance-types", response_model=AdvanceType, status_code=201)
async def create_advance_type(
    body: AdvanceTypeCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    result = await db.execute(
        text("""
            INSERT INTO advance_types (name, max_value)
            VALUES (:name, :max_value)
            RETURNING id::text, name, max_value, is_active
        """),
        body.model_dump(),
    )
    return AdvanceType(**dict(result.fetchone()._mapping))
