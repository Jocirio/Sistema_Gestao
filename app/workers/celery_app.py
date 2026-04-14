from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "gestao_modular",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks_email",
        "app.workers.tasks_pdf",
        "app.workers.tasks_alerts",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Cuiaba",
    enable_utc=True,
    task_track_started=True,
    # Retry automático em falha
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Beat schedule — tarefas periódicas
    beat_schedule={
        # Verificar adiantamentos pendentes todo dia às 8h
        "check-pending-advances-daily": {
            "task": "app.workers.tasks_alerts.check_pending_advances",
            "schedule": 60 * 60 * 24,  # 24h em segundos
        },
        # Verificar SLA vencendo todo dia às 7h
        "check-sla-daily": {
            "task": "app.workers.tasks_alerts.check_sla_alerts",
            "schedule": 60 * 60 * 24,
        },
        # Verificar manutenções de veículos toda semana
        "check-vehicle-maintenance-weekly": {
            "task": "app.workers.tasks_alerts.check_vehicle_maintenance",
            "schedule": 60 * 60 * 24 * 7,
        },
        # Verificar inadimplência todo dia às 9h
        "check-overdue-payments-daily": {
            "task": "app.workers.tasks_alerts.check_overdue_payments",
            "schedule": 60 * 60 * 24,
        },
    },
)
