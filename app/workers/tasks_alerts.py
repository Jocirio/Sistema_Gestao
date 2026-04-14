from app.workers.celery_app import celery_app


@celery_app.task
def check_pending_advances():
    """
    Verifica colaboradores com adiantamento pendente há mais de X dias
    ou com mais de X OS abertas. Envia alerta ao financeiro.
    Roda diariamente via Celery Beat.
    """
    print("[task] Verificando adiantamentos pendentes...")
    # TODO: query na view os_pending_settlements, comparar com limites em company_settings


@celery_app.task
def check_sla_alerts():
    """
    Verifica OS cujo SLA está próximo do vencimento (dentro do prazo de alerta).
    Envia notificação ao gerente responsável.
    """
    print("[task] Verificando SLA de OS...")
    # TODO: query em service_orders com sla_configs cruzado por departure_date


@celery_app.task
def check_vehicle_maintenance():
    """
    Verifica veículos com manutenção agendada para os próximos N dias.
    Envia alerta ao gerente.
    """
    print("[task] Verificando manutenções de veículos...")
    # TODO: query em vehicle_maintenances por scheduled_at e status = 'agendada'


@celery_app.task
def check_overdue_payments():
    """
    Verifica títulos vencidos em financial_entries.
    Aplica régua de cobrança configurada em collection_rules.
    """
    print("[task] Verificando inadimplência...")
    # TODO: query em financial_entries onde due_date < now() e status = 'pendente'
