from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)

# Routers
from app.modules.auth.router import router as auth_router
from app.modules.config.router import router as config_router
from app.modules.clientes.router import router as clientes_router
from app.modules.colaboradores.router import router as colaboradores_router
from app.modules.os.router import router as os_router
from app.modules.comercial.router import router as comercial_router
from app.modules.gerente.router import router as gerente_router
from app.modules.colaborador.router import router as colaborador_router
from app.modules.veiculos.router import router as veiculos_router
from app.modules.financeiro.router import router as financeiro_router


# ---------------------------------------------------------------------------
# Lifespan — startup e shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("✓ Sistema de Gestão Modular iniciando...")
    yield
    # Shutdown
    print("Sistema encerrado.")


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sistema de Gestão Modular",
    description="""
API REST do sistema de gestão modular.

## Módulos disponíveis
- **Auth** — login, refresh de token e perfil do usuário
- **Configurações** — empresa, toggles, funções, setores, adiantamentos
- **Comercial** — agenda, workflow, checklist, orçamentos, diárias
- **Gerente** — O.S., implantação, férias, mapa de calor, estoque
- **Colaborador** — relatórios, fotos, assinaturas, prestação de contas
- **Financeiro** — CP/CR, centro de custo, DRE, fluxo de caixa
- **Veículos** — frota, manutenções, km, custos
- **Portal do cliente** — acesso externo com magic link
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# ---------------------------------------------------------------------------
# Handlers de erro globais
# ---------------------------------------------------------------------------

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


# ---------------------------------------------------------------------------
# Routers — prefixo /api/v1
# ---------------------------------------------------------------------------

API_PREFIX = "/api/v1"

app.include_router(auth_router,          prefix=API_PREFIX)
app.include_router(config_router,        prefix=API_PREFIX)
app.include_router(clientes_router,      prefix=API_PREFIX)
app.include_router(colaboradores_router, prefix=API_PREFIX)
app.include_router(os_router,            prefix=API_PREFIX)
app.include_router(comercial_router,     prefix=API_PREFIX)
app.include_router(gerente_router,       prefix=API_PREFIX)
app.include_router(colaborador_router,   prefix=API_PREFIX)
app.include_router(veiculos_router,      prefix=API_PREFIX)
app.include_router(financeiro_router,    prefix=API_PREFIX)
# app.include_router(comercial_router,    prefix=API_PREFIX)
# app.include_router(gerente_router,      prefix=API_PREFIX)
# app.include_router(os_router,           prefix=API_PREFIX)
# app.include_router(colaborador_router,  prefix=API_PREFIX)
# app.include_router(financeiro_router,   prefix=API_PREFIX)
# app.include_router(veiculos_router,     prefix=API_PREFIX)
# app.include_router(portal_router,       prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["sistema"], summary="Status da API")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": settings.environment,
    }
