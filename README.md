# Sistema de Gestão Modular — API FastAPI + Supabase

## Stack
- **Backend**: Python 3.12 + FastAPI
- **Banco de dados**: PostgreSQL via Supabase
- **ORM**: SQLAlchemy 2.0 (async) + Alembic
- **Filas**: Celery + Redis
- **PDF**: WeasyPrint
- **Storage**: Supabase Storage
- **Auth**: Supabase Auth + JWT próprio

---

## Pré-requisitos
- Python 3.12+
- Docker e Docker Compose
- Conta no Supabase (projeto criado)
- Redis (via Docker ou local)

---

## Configuração inicial

### 1. Clonar e configurar variáveis de ambiente
```bash
git clone <repo>
cd gestao-modular
cp .env.example .env
# Editar .env com as credenciais do Supabase
```

### 2. Preencher o .env com dados do Supabase
No painel do Supabase:
- `SUPABASE_URL` → Settings → API → Project URL
- `SUPABASE_ANON_KEY` → Settings → API → anon public
- `SUPABASE_SERVICE_ROLE_KEY` → Settings → API → service_role secret
- `DATABASE_URL` → Settings → Database → Connection string (mode: asyncpg)
- `JWT_SECRET` → Settings → API → JWT Secret

### 3. Rodar o schema no Supabase
```
Supabase → SQL Editor → colar o conteúdo de schema_supabase_v2.sql → Run
```

### 4. Subir com Docker Compose
```bash
docker compose up --build
```

Serviços disponíveis:
- API: http://localhost:8000
- Docs (Swagger): http://localhost:8000/docs
- Docs (ReDoc): http://localhost:8000/redoc
- Redis: localhost:6379

---

## Rodar localmente (sem Docker)

```bash
# Criar e ativar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Instalar dependências
pip install -r requirements.txt

# Subir apenas o Redis via Docker
docker run -d -p 6379:6379 redis:7-alpine

# Iniciar a API com hot reload
uvicorn app.main:app --reload

# Em outro terminal: iniciar o worker Celery
celery -A app.workers.celery_app worker --loglevel=info

# Em outro terminal: iniciar o agendador Beat (alertas periódicos)
celery -A app.workers.celery_app beat --loglevel=info
```

---

## Estrutura do projeto

```
app/
├── main.py                  # Entry point FastAPI
├── core/
│   ├── config.py            # Variáveis de ambiente (Pydantic Settings)
│   ├── database.py          # Engine SQLAlchemy async + get_db()
│   ├── supabase.py          # Clientes Supabase (anon + admin)
│   ├── security.py          # JWT, autenticação, dependencies de role
│   ├── storage.py           # Upload de arquivos para Supabase Storage
│   ├── exceptions.py        # Exceções e handlers globais
│   └── pagination.py        # Paginação reutilizável
├── modules/
│   ├── auth/                # Login, refresh, /me
│   ├── config/              # Empresa, toggles, funções, setores, adiantamentos
│   ├── os/                  # Sub-módulo Ordem de Serviço (próximo módulo)
│   ├── comercial/           # Agenda, workflow, checklist, orçamentos
│   ├── gerente/             # Implantação, férias, SLA, estoque
│   ├── colaborador/         # Relatórios, fotos, assinaturas, prestação de contas
│   ├── financeiro/          # CP/CR, centro de custo, DRE, conciliação
│   ├── veiculos/            # Frota, manutenções, km, custos
│   └── portal/              # Portal externo do cliente (magic link)
└── workers/
    ├── celery_app.py        # Configuração Celery + Beat schedule
    ├── tasks_email.py       # Envio de e-mails assíncronos
    ├── tasks_pdf.py         # Geração de PDF (OS e relatórios)
    └── tasks_alerts.py      # Alertas periódicos (SLA, inadimplência, etc.)

alembic/                     # Migrations (inicializar com: alembic init alembic)
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

---

## Endpoints disponíveis (base)

### Auth
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/v1/auth/login` | Login com e-mail e senha |
| POST | `/api/v1/auth/refresh` | Renovar access token |
| GET  | `/api/v1/auth/me` | Perfil do usuário logado |

### Configurações
| Método | Rota | Descrição |
|--------|------|-----------|
| GET    | `/api/v1/config/company` | Dados da empresa |
| PATCH  | `/api/v1/config/company` | Atualizar dados da empresa |
| POST   | `/api/v1/config/company/logo` | Upload da logo |
| GET    | `/api/v1/config/features` | Listar feature toggles |
| PATCH  | `/api/v1/config/features/{module}/{key}` | Habilitar/desabilitar feature |
| GET    | `/api/v1/config/job-functions` | Funções de colaboradores |
| POST   | `/api/v1/config/job-functions` | Criar função |
| GET    | `/api/v1/config/os-sectors` | Setores de OS |
| POST   | `/api/v1/config/os-sectors` | Criar setor |
| GET    | `/api/v1/config/advance-types` | Tipos de adiantamento |
| POST   | `/api/v1/config/advance-types` | Criar tipo |

### Sistema
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Status da API |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |

---

## Próximos módulos a desenvolver
1. `modules/os/` — Sub-módulo Ordem de Serviço (mais crítico)
2. `modules/comercial/` — Clientes, workflow, agenda
3. `modules/colaborador/` — Relatórios com fotos e assinaturas
4. `modules/financeiro/` — Lançamentos, DRE, fluxo de caixa
5. `modules/veiculos/` — Frota e custos
6. `modules/gerente/` — Implantação, SLA, estoque
7. `modules/portal/` — Portal externo do cliente

---

## Autenticação

Todas as rotas (exceto `/health` e `/api/v1/auth/login`) exigem o header:
```
Authorization: Bearer <access_token>
```

O token expira em 60 minutos. Use `/api/v1/auth/refresh` com o `refresh_token`
para obter um novo par de tokens sem precisar fazer login novamente.

### Roles disponíveis
| Role | Acesso |
|------|--------|
| `admin` | Acesso total a todos os módulos |
| `gerente` | Gerente + leitura de colaboradores |
| `comercial` | Módulo comercial + cadastro de clientes |
| `colaborador` | Apenas próprias OS e relatórios |
| `financeiro` | Módulo financeiro + leitura de OS |

---

## Configuração dos buckets no Supabase Storage

Criar os seguintes buckets em Supabase → Storage:
- `report-photos` — fotos dos relatórios de atendimento (público)
- `report-signatures` — assinaturas digitais (privado)
- `documents` — contratos e anexos (privado)
- `company-logos` — logo da empresa (público)
