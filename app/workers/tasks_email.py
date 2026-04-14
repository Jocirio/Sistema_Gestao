from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_report_email(self, report_id: str):
    """
    Envia o relatório de atendimento por e-mail aos destinatários cadastrados.
    Chamado automaticamente ao finalizar um relatório no módulo colaborador.
    """
    try:
        # Import local para evitar circular imports
        from app.core.config import settings
        import httpx

        # Busca dados do relatório via API interna
        # (em produção, usar SQLAlchemy direto com sessão síncrona)
        print(f"[task] Enviando relatório {report_id} por e-mail")
        # TODO: implementar envio via FastAPI-Mail

    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_magic_link_email(self, portal_user_id: str, token: str, user_email: str):
    """
    Envia o magic link de acesso ao portal do cliente.
    """
    try:
        print(f"[task] Enviando magic link para {user_email}")
        # TODO: implementar envio via FastAPI-Mail

    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_email(self, to_email: str, subject: str, body: str):
    """Envia e-mail de notificação genérico."""
    try:
        print(f"[task] Notificação para {to_email}: {subject}")
        # TODO: implementar envio via FastAPI-Mail

    except Exception as exc:
        raise self.retry(exc=exc)
