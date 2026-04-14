from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_user, require_financeiro, TokenData
from app.core.pagination import Page, PaginationParams, pagination_params

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


# ---------------------------------------------------------------------------
# Schemas — Fornecedores
# ---------------------------------------------------------------------------

class SupplierCreate(BaseModel):
    name: str
    cnpj: str | None = None
    email: str | None = None
    phone: str | None = None


class SupplierResponse(BaseModel):
    id: str
    name: str
    cnpj: str | None
    email: str | None
    phone: str | None
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Contas bancárias
# ---------------------------------------------------------------------------

class BankAccountCreate(BaseModel):
    bank_name: str
    agency: str | None = None
    account: str | None = None
    account_type: str = "corrente"


class BankAccountResponse(BaseModel):
    id: str
    bank_name: str
    agency: str | None
    account: str | None
    account_type: str
    balance: float
    is_active: bool
    created_at: str


class BankAccountBalanceUpdate(BaseModel):
    balance: float


# ---------------------------------------------------------------------------
# Schemas — Categorias financeiras
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str
    type: str          # pagar | receber
    parent_id: str | None = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    type: str
    parent_id: str | None
    parent_name: str | None
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Lançamentos financeiros
# ---------------------------------------------------------------------------

class EntryCreate(BaseModel):
    type: str              # pagar | receber
    description: str
    amount: float
    due_date: str          # ISO date
    client_id: str | None = None
    supplier_id: str | None = None
    service_order_id: str | None = None
    cost_center_id: str | None = None
    category_id: str | None = None
    bank_account_id: str | None = None
    invoice_number: str | None = None
    attachment_url: str | None = None
    notes: str | None = None
    is_recurring: bool = False
    recurrence_day: int | None = None


class EntryUpdate(BaseModel):
    description: str | None = None
    amount: float | None = None
    due_date: str | None = None
    status: str | None = None   # pendente, pago, vencido, cancelado
    paid_at: str | None = None
    paid_amount: float | None = None
    bank_account_id: str | None = None
    invoice_number: str | None = None
    attachment_url: str | None = None
    notes: str | None = None


class EntryResponse(BaseModel):
    id: str
    type: str
    description: str
    amount: float
    due_date: str
    paid_at: str | None
    paid_amount: float | None
    status: str
    client_id: str | None
    client_name: str | None
    supplier_id: str | None
    supplier_name: str | None
    service_order_id: str | None
    os_number: str | None
    cost_center_id: str | None
    cost_center_name: str | None
    category_id: str | None
    category_name: str | None
    bank_account_id: str | None
    bank_name: str | None
    invoice_number: str | None
    attachment_url: str | None
    notes: str | None
    is_recurring: bool
    recurrence_day: int | None
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str
    days_overdue: int | None


class EntryPayment(BaseModel):
    paid_amount: float
    paid_at: str          # ISO date
    bank_account_id: str | None = None


# ---------------------------------------------------------------------------
# Schemas — Centro de custo
# ---------------------------------------------------------------------------

class CostCenterCreate(BaseModel):
    name: str
    description: str | None = None


class CostCenterResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Schemas — Conciliação bancária
# ---------------------------------------------------------------------------

class ReconcileRequest(BaseModel):
    transaction_id: str
    financial_entry_id: str


# ---------------------------------------------------------------------------
# Schemas — Provisão de RH
# ---------------------------------------------------------------------------

class RHProvisionCreate(BaseModel):
    collaborator_id: str
    reference_month: str   # ISO date (primeiro dia do mês)
    gross_salary: float
    provision_13th: float | None = None
    provision_vacation: float | None = None
    provision_fgts: float | None = None
    provision_inss_employer: float | None = None


class RHProvisionResponse(BaseModel):
    id: str
    collaborator_id: str
    collaborator_name: str
    reference_month: str
    gross_salary: float
    provision_13th: float | None
    provision_vacation: float | None
    provision_fgts: float | None
    provision_inss_employer: float | None
    total_provision: float
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENTRY_SELECT = """
    SELECT
        fe.id::text,
        fe.type,
        fe.description,
        fe.amount,
        fe.due_date::text,
        fe.paid_at::text,
        fe.paid_amount,
        fe.status,
        fe.client_id::text,
        cl.name             as client_name,
        fe.supplier_id::text,
        su.name             as supplier_name,
        fe.service_order_id::text,
        so.os_number,
        fe.cost_center_id::text,
        cc.name             as cost_center_name,
        fe.category_id::text,
        cat.name            as category_name,
        fe.bank_account_id::text,
        ba.bank_name,
        fe.invoice_number,
        fe.attachment_url,
        fe.notes,
        fe.is_recurring,
        fe.recurrence_day,
        fe.created_by::text,
        p.full_name         as created_by_name,
        fe.created_at::text,
        fe.updated_at::text,
        CASE
            WHEN fe.status = 'pendente' AND fe.due_date < current_date
            THEN (current_date - fe.due_date)
            ELSE null
        END                 as days_overdue
    FROM financial_entries fe
    LEFT JOIN clients cl            ON cl.id  = fe.client_id
    LEFT JOIN suppliers su          ON su.id  = fe.supplier_id
    LEFT JOIN service_orders so     ON so.id  = fe.service_order_id
    LEFT JOIN cost_centers cc       ON cc.id  = fe.cost_center_id
    LEFT JOIN financial_categories cat ON cat.id = fe.category_id
    LEFT JOIN bank_accounts ba      ON ba.id  = fe.bank_account_id
    LEFT JOIN profiles p            ON p.id   = fe.created_by
"""


def row_to_entry(row) -> EntryResponse:
    m = dict(row._mapping)
    return EntryResponse(
        id=str(m["id"]),
        type=m["type"],
        description=m["description"],
        amount=float(m["amount"]),
        due_date=str(m["due_date"]),
        paid_at=str(m["paid_at"]) if m.get("paid_at") else None,
        paid_amount=float(m["paid_amount"]) if m.get("paid_amount") else None,
        status=m["status"],
        client_id=str(m["client_id"]) if m.get("client_id") else None,
        client_name=m.get("client_name"),
        supplier_id=str(m["supplier_id"]) if m.get("supplier_id") else None,
        supplier_name=m.get("supplier_name"),
        service_order_id=str(m["service_order_id"]) if m.get("service_order_id") else None,
        os_number=m.get("os_number"),
        cost_center_id=str(m["cost_center_id"]) if m.get("cost_center_id") else None,
        cost_center_name=m.get("cost_center_name"),
        category_id=str(m["category_id"]) if m.get("category_id") else None,
        category_name=m.get("category_name"),
        bank_account_id=str(m["bank_account_id"]) if m.get("bank_account_id") else None,
        bank_name=m.get("bank_name"),
        invoice_number=m.get("invoice_number"),
        attachment_url=m.get("attachment_url"),
        notes=m.get("notes"),
        is_recurring=m.get("is_recurring", False),
        recurrence_day=m.get("recurrence_day"),
        created_by=str(m["created_by"]),
        created_by_name=m.get("created_by_name", ""),
        created_at=str(m["created_at"]),
        updated_at=str(m["updated_at"]),
        days_overdue=int(m["days_overdue"]) if m.get("days_overdue") else None,
    )


# ---------------------------------------------------------------------------
# Endpoints — Fornecedores
# ---------------------------------------------------------------------------

@router.get("/fornecedores", response_model=list[SupplierResponse], summary="Listar fornecedores")
async def listar_fornecedores(
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    conditions = ["is_active = true"]
    params: dict[str, Any] = {}
    if search:
        conditions.append("(lower(name) ilike lower(:search) OR cnpj ilike :search)")
        params["search"] = f"%{search}%"

    result = await db.execute(
        text(f"""
            SELECT id::text, name, cnpj, email, phone, is_active, created_at::text
            FROM suppliers WHERE {" AND ".join(conditions)} ORDER BY name
        """),
        params,
    )
    return [SupplierResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/fornecedores", response_model=SupplierResponse, status_code=201, summary="Criar fornecedor")
async def criar_fornecedor(
    body: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            INSERT INTO suppliers (name, cnpj, email, phone)
            VALUES (:name, :cnpj, :email, :phone)
            RETURNING id::text, name, cnpj, email, phone, is_active, created_at::text
        """),
        body.model_dump(),
    )
    return SupplierResponse(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Contas bancárias
# ---------------------------------------------------------------------------

@router.get("/contas-bancarias", response_model=list[BankAccountResponse], summary="Listar contas bancárias")
async def listar_contas_bancarias(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            SELECT id::text, bank_name, agency, account, account_type,
                   balance, is_active, created_at::text
            FROM bank_accounts WHERE is_active = true ORDER BY bank_name
        """)
    )
    return [
        BankAccountResponse(**{**dict(r._mapping), "balance": float(dict(r._mapping)["balance"])})
        for r in result.fetchall()
    ]


@router.post("/contas-bancarias", response_model=BankAccountResponse, status_code=201, summary="Cadastrar conta bancária")
async def criar_conta_bancaria(
    body: BankAccountCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            INSERT INTO bank_accounts (bank_name, agency, account, account_type)
            VALUES (:bank_name, :agency, :account, :account_type)
            RETURNING id::text, bank_name, agency, account, account_type,
                      balance, is_active, created_at::text
        """),
        body.model_dump(),
    )
    m = dict(result.fetchone()._mapping)
    return BankAccountResponse(**{**m, "balance": float(m["balance"])})


# ---------------------------------------------------------------------------
# Endpoints — Categorias
# ---------------------------------------------------------------------------

@router.get("/categorias", response_model=list[CategoryResponse], summary="Listar categorias")
async def listar_categorias(
    type: str | None = Query(None, description="pagar | receber"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    conditions = ["c.is_active = true"]
    params: dict[str, Any] = {}
    if type:
        conditions.append("c.type = :type")
        params["type"] = type

    result = await db.execute(
        text(f"""
            SELECT c.id::text, c.name, c.type, c.parent_id::text,
                   p.name as parent_name, c.is_active, c.created_at::text
            FROM financial_categories c
            LEFT JOIN financial_categories p ON p.id = c.parent_id
            WHERE {" AND ".join(conditions)}
            ORDER BY c.type, c.name
        """),
        params,
    )
    return [CategoryResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/categorias", response_model=CategoryResponse, status_code=201, summary="Criar categoria")
async def criar_categoria(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    if body.type not in ("pagar", "receber"):
        raise HTTPException(status_code=400, detail="type deve ser 'pagar' ou 'receber'")

    result = await db.execute(
        text("""
            INSERT INTO financial_categories (name, type, parent_id)
            VALUES (:name, :type, :parent_id)
            RETURNING id::text, name, type, parent_id::text, is_active, created_at::text
        """),
        body.model_dump(),
    )
    m = dict(result.fetchone()._mapping)
    m["parent_name"] = None
    return CategoryResponse(**m)


# ---------------------------------------------------------------------------
# Endpoints — Centro de custo
# ---------------------------------------------------------------------------

@router.get("/centros-de-custo", response_model=list[CostCenterResponse], summary="Listar centros de custo")
async def listar_centros_custo(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id::text, name, description, is_active, created_at::text FROM cost_centers WHERE is_active = true ORDER BY name")
    )
    return [CostCenterResponse(**dict(r._mapping)) for r in result.fetchall()]


@router.post("/centros-de-custo", response_model=CostCenterResponse, status_code=201, summary="Criar centro de custo")
async def criar_centro_custo(
    body: CostCenterCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            INSERT INTO cost_centers (name, description)
            VALUES (:name, :description)
            RETURNING id::text, name, description, is_active, created_at::text
        """),
        body.model_dump(),
    )
    return CostCenterResponse(**dict(result.fetchone()._mapping))


# ---------------------------------------------------------------------------
# Endpoints — Lançamentos (contas a pagar e a receber)
# ---------------------------------------------------------------------------

@router.get("/lancamentos", response_model=Page[EntryResponse], summary="Listar lançamentos")
async def listar_lancamentos(
    type: str | None = Query(None, description="pagar | receber"),
    status: str | None = Query(None, description="pendente, pago, vencido, cancelado"),
    client_id: str | None = Query(None),
    supplier_id: str | None = Query(None),
    cost_center_id: str | None = Query(None),
    due_from: str | None = Query(None, description="Vencimento a partir de (YYYY-MM-DD)"),
    due_to: str | None = Query(None, description="Vencimento até (YYYY-MM-DD)"),
    overdue_only: bool | None = Query(None, description="Apenas vencidos"),
    pagination: PaginationParams = Depends(pagination_params),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if type:
        conditions.append("fe.type = :type")
        params["type"] = type
    if status:
        conditions.append("fe.status = :status")
        params["status"] = status
    if client_id:
        conditions.append("fe.client_id = :client_id")
        params["client_id"] = client_id
    if supplier_id:
        conditions.append("fe.supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if cost_center_id:
        conditions.append("fe.cost_center_id = :cost_center_id")
        params["cost_center_id"] = cost_center_id
    if due_from:
        conditions.append("fe.due_date >= :due_from")
        params["due_from"] = due_from
    if due_to:
        conditions.append("fe.due_date <= :due_to")
        params["due_to"] = due_to
    if overdue_only:
        conditions.append("fe.status = 'pendente' AND fe.due_date < current_date")

    where = " AND ".join(conditions)

    count = await db.execute(
        text(f"SELECT count(*) FROM financial_entries fe WHERE {where}"), params
    )
    total = count.scalar()
    params["limit"] = pagination.limit
    params["offset"] = pagination.offset

    result = await db.execute(
        text(f"{ENTRY_SELECT} WHERE {where} ORDER BY fe.due_date ASC LIMIT :limit OFFSET :offset"),
        params,
    )
    items = [row_to_entry(r) for r in result.fetchall()]
    return Page.create(items=items, total=total, params=pagination)


@router.post("/lancamentos", response_model=EntryResponse, status_code=201, summary="Criar lançamento")
async def criar_lancamento(
    body: EntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_financeiro),
):
    if body.type not in ("pagar", "receber"):
        raise HTTPException(status_code=400, detail="type deve ser 'pagar' ou 'receber'")

    result = await db.execute(
        text("""
            INSERT INTO financial_entries (
                type, description, amount, due_date,
                client_id, supplier_id, service_order_id,
                cost_center_id, category_id, bank_account_id,
                invoice_number, attachment_url, notes,
                is_recurring, recurrence_day, created_by
            ) VALUES (
                :type, :description, :amount, :due_date,
                :client_id, :supplier_id, :service_order_id,
                :cost_center_id, :category_id, :bank_account_id,
                :invoice_number, :attachment_url, :notes,
                :is_recurring, :recurrence_day, :created_by
            )
            RETURNING id::text
        """),
        {**body.model_dump(), "created_by": str(current_user.user_id)},
    )
    entry_id = result.fetchone().id
    full = await db.execute(text(f"{ENTRY_SELECT} WHERE fe.id = :id"), {"id": entry_id})
    return row_to_entry(full.fetchone())


@router.get("/lancamentos/{entry_id}", response_model=EntryResponse, summary="Buscar lançamento")
async def buscar_lancamento(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text(f"{ENTRY_SELECT} WHERE fe.id = :id"), {"id": str(entry_id)}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")
    return row_to_entry(row)


@router.patch("/lancamentos/{entry_id}", response_model=EntryResponse, summary="Atualizar lançamento")
async def atualizar_lancamento(
    entry_id: UUID,
    body: EntryUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(entry_id)

    result = await db.execute(
        text(f"UPDATE financial_entries SET {set_clause}, updated_at = now() WHERE id = :id RETURNING id"),
        updates,
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    full = await db.execute(text(f"{ENTRY_SELECT} WHERE fe.id = :id"), {"id": str(entry_id)})
    return row_to_entry(full.fetchone())


@router.post("/lancamentos/{entry_id}/pagar", response_model=EntryResponse, summary="Registrar pagamento")
async def pagar_lancamento(
    entry_id: UUID,
    body: EntryPayment,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """Registra o pagamento ou recebimento de um lançamento."""
    await db.execute(
        text("""
            UPDATE financial_entries SET
                status          = 'pago',
                paid_at         = :paid_at,
                paid_amount     = :paid_amount,
                bank_account_id = coalesce(:bank_account_id::uuid, bank_account_id),
                updated_at      = now()
            WHERE id = :id AND status = 'pendente'
        """),
        {
            "id": str(entry_id),
            "paid_at": body.paid_at,
            "paid_amount": body.paid_amount,
            "bank_account_id": body.bank_account_id,
        },
    )
    full = await db.execute(text(f"{ENTRY_SELECT} WHERE fe.id = :id"), {"id": str(entry_id)})
    return row_to_entry(full.fetchone())


@router.delete("/lancamentos/{entry_id}", status_code=204, summary="Cancelar lançamento")
async def cancelar_lancamento(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            UPDATE financial_entries SET status = 'cancelado', updated_at = now()
            WHERE id = :id AND status = 'pendente'
            RETURNING id
        """),
        {"id": str(entry_id)},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Lançamento não encontrado ou já pago/cancelado")


# ---------------------------------------------------------------------------
# Endpoints — Conciliação bancária
# ---------------------------------------------------------------------------

@router.get("/conciliacao/transacoes", summary="Transações do extrato não conciliadas")
async def transacoes_nao_conciliadas(
    bank_account_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    conditions = ["bt.reconciled = false"]
    params: dict[str, Any] = {}
    if bank_account_id:
        conditions.append("bt.bank_account_id = :bank_account_id")
        params["bank_account_id"] = bank_account_id

    result = await db.execute(
        text(f"""
            SELECT
                bt.id::text, bt.bank_account_id::text, ba.bank_name,
                bt.transaction_date::text, bt.description,
                bt.amount, bt.reconciled
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.bank_account_id
            WHERE {" AND ".join(conditions)}
            ORDER BY bt.transaction_date DESC
        """),
        params,
    )
    return [dict(r._mapping) for r in result.fetchall()]


@router.post("/conciliacao/reconciliar", summary="Conciliar transação com lançamento")
async def reconciliar(
    body: ReconcileRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    result = await db.execute(
        text("""
            UPDATE bank_transactions SET
                reconciled         = true,
                financial_entry_id = :financial_entry_id::uuid
            WHERE id = :transaction_id AND reconciled = false
            RETURNING id
        """),
        {"transaction_id": body.transaction_id, "financial_entry_id": body.financial_entry_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Transação não encontrada ou já conciliada")
    return {"message": "Transação conciliada com sucesso"}


# ---------------------------------------------------------------------------
# Endpoints — Relatórios financeiros
# ---------------------------------------------------------------------------

@router.get("/relatorios/fluxo-de-caixa", summary="Fluxo de caixa por período")
async def fluxo_de_caixa(
    date_from: str = Query(..., description="Data inicial (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Data final (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """
    Fluxo de caixa agrupado por data — entradas e saídas previstas e realizadas.
    """
    result = await db.execute(
        text("""
            SELECT
                due_date::text                                                      as data,
                coalesce(sum(amount) filter (where type = 'receber'), 0)            as entradas_previstas,
                coalesce(sum(paid_amount) filter (where type = 'receber' AND status = 'pago'), 0) as entradas_realizadas,
                coalesce(sum(amount) filter (where type = 'pagar'), 0)              as saidas_previstas,
                coalesce(sum(paid_amount) filter (where type = 'pagar' AND status = 'pago'), 0)   as saidas_realizadas
            FROM financial_entries
            WHERE due_date BETWEEN :date_from AND :date_to
            GROUP BY due_date
            ORDER BY due_date
        """),
        {"date_from": date_from, "date_to": date_to},
    )
    rows = [dict(r._mapping) for r in result.fetchall()]

    # Calcular saldo acumulado
    saldo = 0.0
    for row in rows:
        entradas = float(row["entradas_realizadas"])
        saidas = float(row["saidas_realizadas"])
        saldo += entradas - saidas
        row["saldo_acumulado"] = round(saldo, 2)
        row["entradas_previstas"] = float(row["entradas_previstas"])
        row["entradas_realizadas"] = float(row["entradas_realizadas"])
        row["saidas_previstas"] = float(row["saidas_previstas"])
        row["saidas_realizadas"] = float(row["saidas_realizadas"])

    return {"periodo": {"de": date_from, "ate": date_to}, "fluxo": rows}


@router.get("/relatorios/dre", summary="DRE simplificada por período")
async def dre(
    date_from: str = Query(..., description="Data inicial (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Data final (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """
    Demonstração de Resultado do Exercício simplificada.
    Agrupa receitas e custos por categoria.
    """
    result = await db.execute(
        text("""
            SELECT
                fe.type,
                coalesce(cat.name, 'Sem categoria')     as categoria,
                sum(fe.amount)                           as valor_previsto,
                coalesce(sum(fe.paid_amount) filter (where fe.status = 'pago'), 0) as valor_realizado,
                count(*)                                 as total_lancamentos
            FROM financial_entries fe
            LEFT JOIN financial_categories cat ON cat.id = fe.category_id
            WHERE fe.due_date BETWEEN :date_from AND :date_to
            GROUP BY fe.type, cat.name
            ORDER BY fe.type, categoria
        """),
        {"date_from": date_from, "date_to": date_to},
    )
    rows = result.fetchall()

    receitas_prev = sum(float(r.valor_previsto) for r in rows if r.type == "receber")
    receitas_real = sum(float(r.valor_realizado) for r in rows if r.type == "receber")
    custos_prev = sum(float(r.valor_previsto) for r in rows if r.type == "pagar")
    custos_real = sum(float(r.valor_realizado) for r in rows if r.type == "pagar")

    return {
        "periodo": {"de": date_from, "ate": date_to},
        "resumo": {
            "receitas_previstas": round(receitas_prev, 2),
            "receitas_realizadas": round(receitas_real, 2),
            "custos_previstos": round(custos_prev, 2),
            "custos_realizados": round(custos_real, 2),
            "lucro_previsto": round(receitas_prev - custos_prev, 2),
            "lucro_realizado": round(receitas_real - custos_real, 2),
            "margem_pct": round(((receitas_real - custos_real) / receitas_real * 100) if receitas_real > 0 else 0, 2),
        },
        "detalhamento": [
            {
                "tipo": r.type,
                "categoria": r.categoria,
                "valor_previsto": float(r.valor_previsto),
                "valor_realizado": float(r.valor_realizado),
                "lancamentos": r.total_lancamentos,
            }
            for r in rows
        ],
    }


@router.get("/relatorios/coeficiente-clientes", summary="Coeficiente de participação por cliente")
async def coeficiente_clientes(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """
    Participação percentual de cada cliente na receita total.
    Usa a view client_financial_summary do banco.
    """
    result = await db.execute(
        text("""
            SELECT
                client_id::text,
                client_name,
                contract_value,
                total_costs,
                total_received,
                revenue_participation_pct
            FROM client_financial_summary
            ORDER BY revenue_participation_pct DESC
        """)
    )
    return [
        {
            **dict(r._mapping),
            "contract_value": float(dict(r._mapping)["contract_value"]) if dict(r._mapping).get("contract_value") else None,
            "total_costs": float(dict(r._mapping)["total_costs"]),
            "total_received": float(dict(r._mapping)["total_received"]),
            "revenue_participation_pct": float(dict(r._mapping)["revenue_participation_pct"]),
        }
        for r in result.fetchall()
    ]


@router.get("/relatorios/inadimplencia", summary="Relatório de inadimplência")
async def inadimplencia(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """Lista todos os títulos vencidos com dias em atraso e cliente/fornecedor."""
    result = await db.execute(
        text(f"""
            {ENTRY_SELECT}
            WHERE fe.status = 'pendente'
            AND fe.type = 'receber'
            AND fe.due_date < current_date
            ORDER BY fe.due_date ASC
        """)
    )
    return [row_to_entry(r) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Endpoints — Provisão de RH
# ---------------------------------------------------------------------------

@router.get("/rh-provisoes", response_model=list[RHProvisionResponse], summary="Listar provisões de RH")
async def listar_provisoes(
    collaborator_id: str | None = Query(None),
    reference_month: str | None = Query(None, description="YYYY-MM-01"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if collaborator_id:
        conditions.append("rp.collaborator_id = :collaborator_id")
        params["collaborator_id"] = collaborator_id
    if reference_month:
        conditions.append("rp.reference_month = :reference_month")
        params["reference_month"] = reference_month

    result = await db.execute(
        text(f"""
            SELECT
                rp.id::text, rp.collaborator_id::text,
                p.full_name         as collaborator_name,
                rp.reference_month::text,
                rp.gross_salary,
                rp.provision_13th,
                rp.provision_vacation,
                rp.provision_fgts,
                rp.provision_inss_employer,
                rp.total_provision,
                rp.created_at::text
            FROM rh_provisions rp
            JOIN profiles p ON p.id = rp.collaborator_id
            WHERE {" AND ".join(conditions)}
            ORDER BY rp.reference_month DESC, p.full_name
        """),
        params,
    )
    return [
        RHProvisionResponse(**{
            **dict(r._mapping),
            "id": str(dict(r._mapping)["id"]),
            "collaborator_id": str(dict(r._mapping)["collaborator_id"]),
            "gross_salary": float(dict(r._mapping)["gross_salary"]),
            "provision_13th": float(dict(r._mapping)["provision_13th"]) if dict(r._mapping).get("provision_13th") else None,
            "provision_vacation": float(dict(r._mapping)["provision_vacation"]) if dict(r._mapping).get("provision_vacation") else None,
            "provision_fgts": float(dict(r._mapping)["provision_fgts"]) if dict(r._mapping).get("provision_fgts") else None,
            "provision_inss_employer": float(dict(r._mapping)["provision_inss_employer"]) if dict(r._mapping).get("provision_inss_employer") else None,
            "total_provision": float(dict(r._mapping)["total_provision"]),
        })
        for r in result.fetchall()
    ]


@router.post("/rh-provisoes", response_model=RHProvisionResponse, status_code=201, summary="Lançar provisão de RH")
async def criar_provisao(
    body: RHProvisionCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """
    Lança provisão mensal de RH. O banco calcula total_provision automaticamente.
    Se já existir provisão para o mesmo colaborador e mês, atualiza.
    """
    result = await db.execute(
        text("""
            INSERT INTO rh_provisions
                (collaborator_id, reference_month, gross_salary,
                 provision_13th, provision_vacation, provision_fgts, provision_inss_employer)
            VALUES
                (:collaborator_id, :reference_month, :gross_salary,
                 :provision_13th, :provision_vacation, :provision_fgts, :provision_inss_employer)
            ON CONFLICT (collaborator_id, reference_month) DO UPDATE SET
                gross_salary            = EXCLUDED.gross_salary,
                provision_13th          = EXCLUDED.provision_13th,
                provision_vacation      = EXCLUDED.provision_vacation,
                provision_fgts          = EXCLUDED.provision_fgts,
                provision_inss_employer = EXCLUDED.provision_inss_employer
            RETURNING id::text
        """),
        body.model_dump(),
    )
    prov_id = result.fetchone().id

    full = await db.execute(
        text("""
            SELECT rp.id::text, rp.collaborator_id::text, p.full_name as collaborator_name,
                   rp.reference_month::text, rp.gross_salary, rp.provision_13th,
                   rp.provision_vacation, rp.provision_fgts, rp.provision_inss_employer,
                   rp.total_provision, rp.created_at::text
            FROM rh_provisions rp
            JOIN profiles p ON p.id = rp.collaborator_id
            WHERE rp.id = :id
        """),
        {"id": prov_id},
    )
    m = dict(full.fetchone()._mapping)
    return RHProvisionResponse(**{
        **m,
        "id": str(m["id"]),
        "collaborator_id": str(m["collaborator_id"]),
        "gross_salary": float(m["gross_salary"]),
        "provision_13th": float(m["provision_13th"]) if m.get("provision_13th") else None,
        "provision_vacation": float(m["provision_vacation"]) if m.get("provision_vacation") else None,
        "provision_fgts": float(m["provision_fgts"]) if m.get("provision_fgts") else None,
        "provision_inss_employer": float(m["provision_inss_employer"]) if m.get("provision_inss_employer") else None,
        "total_provision": float(m["total_provision"]),
    })


# ---------------------------------------------------------------------------
# Endpoints — Dashboard financeiro
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Dashboard financeiro")
async def dashboard_financeiro(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_financeiro),
):
    """KPIs consolidados para o painel do financeiro."""

    # Totais a pagar e a receber
    totais = await db.execute(
        text("""
            SELECT
                coalesce(sum(amount) filter (where type = 'receber' AND status = 'pendente'), 0) as a_receber,
                coalesce(sum(amount) filter (where type = 'pagar'   AND status = 'pendente'), 0) as a_pagar,
                coalesce(sum(amount) filter (where type = 'receber' AND status = 'pendente' AND due_date < current_date), 0) as inadimplencia,
                coalesce(sum(amount) filter (where type = 'pagar'   AND status = 'pendente' AND due_date < current_date), 0) as vencidos_a_pagar,
                count(*) filter (where status = 'pendente' AND due_date < current_date) as total_vencidos
            FROM financial_entries
        """)
    )
    t = dict(totais.fetchone()._mapping)

    # Adiantamentos pendentes de devolução
    adiantamentos = await db.execute(
        text("SELECT count(*), coalesce(sum(abs(balance)), 0) as total FROM service_orders WHERE settlement_status = 'pendente_devolucao'")
    )
    ad = dict(adiantamentos.fetchone()._mapping)

    # Férias aprovadas este mês com impacto financeiro
    ferias = await db.execute(
        text("""
            SELECT coalesce(sum(financial_impact), 0) as impacto_ferias
            FROM vacation_requests
            WHERE status = 'aprovada'
            AND start_date >= date_trunc('month', current_date)
        """)
    )
    ferias_impacto = float(ferias.scalar() or 0)

    # Receita do mês atual
    receita_mes = await db.execute(
        text("""
            SELECT coalesce(sum(paid_amount), 0)
            FROM financial_entries
            WHERE type = 'receber' AND status = 'pago'
            AND paid_at >= date_trunc('month', current_date)
        """)
    )

    return {
        "a_receber": float(t["a_receber"]),
        "a_pagar": float(t["a_pagar"]),
        "saldo_previsto": round(float(t["a_receber"]) - float(t["a_pagar"]), 2),
        "inadimplencia": float(t["inadimplencia"]),
        "vencidos_a_pagar": float(t["vencidos_a_pagar"]),
        "total_titulos_vencidos": int(t["total_vencidos"]),
        "adiantamentos_pendentes": int(ad["count"]),
        "valor_adiantamentos_pendentes": float(ad["total"]),
        "impacto_ferias_mes": ferias_impacto,
        "receita_mes_atual": float(receita_mes.scalar() or 0),
    }
