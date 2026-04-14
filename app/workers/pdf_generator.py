"""
Gerador de PDF usando WeasyPrint + Jinja2.
Chamado pelas tasks Celery tasks_pdf.py.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _render_html(template_name: str, context: dict) -> str:
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def generate_os_pdf(context: dict) -> bytes:
    """
    Gera o PDF de uma Ordem de Serviço.
    context deve conter: os, company, advances, generated_at
    """
    if "generated_at" not in context:
        context["generated_at"] = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

    html_content = _render_html("os.html", context)
    pdf_bytes = HTML(string=html_content).write_pdf(
        stylesheets=[
            CSS(string="""
                @page {
                    size: A4;
                    margin: 1.5cm 1.8cm;
                }
            """)
        ]
    )
    return pdf_bytes


def generate_report_pdf(context: dict) -> bytes:
    """
    Gera o PDF de um relatório de atendimento.
    context deve conter: report, company, photos, signatures,
                         recipients, checklist_items, generated_at
    """
    if "generated_at" not in context:
        context["generated_at"] = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

    html_content = _render_html("relatorio.html", context)
    pdf_bytes = HTML(string=html_content).write_pdf(
        stylesheets=[
            CSS(string="""
                @page {
                    size: A4;
                    margin: 1.5cm 1.8cm;
                }
            """)
        ]
    )
    return pdf_bytes
