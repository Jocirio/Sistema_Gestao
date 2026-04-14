from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_os_pdf(self, service_order_id: str):
    """
    Gera o PDF da Ordem de Serviço com timbre da empresa.
    Usa WeasyPrint para renderizar HTML → PDF.
    O PDF é salvo no Supabase Storage e a URL atualizada na OS.
    """
    try:
        print(f"[task] Gerando PDF da OS {service_order_id}")
        # TODO: buscar dados da OS, renderizar template Jinja2, gerar PDF com WeasyPrint

    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report_pdf(self, report_id: str):
    """
    Gera o PDF do relatório de atendimento com fotos e assinaturas.
    Salva no Supabase Storage e atualiza pdf_url no service_reports.
    """
    try:
        print(f"[task] Gerando PDF do relatório {report_id}")
        # TODO: buscar dados, fotos e assinaturas, renderizar template, gerar PDF

    except Exception as exc:
        raise self.retry(exc=exc)
