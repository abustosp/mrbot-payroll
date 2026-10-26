"""Rutas de la interfaz web (Jinja2 + HTMX).

Montaje en la aplicacion principal::

    from app.web.routes import router as web_router
    app.include_router(web_router)

No se registran handlers globales de la aplicacion ni se monta ``StaticFiles``:
el CSS y el JS locales se sirven desde este mismo router. Las rutas no
duplican reglas de liquidacion; solo leen del repositorio inyectado y
presentan los datos.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.exporters.pdf.receipts import (
    ReceiptContextError,
    pdf_backend_status,
    render_receipt_html,
    render_receipt_pdf,
    render_receipts_zip,
)
from app.web.dependencies import get_data_source
from app.web.formatting import (
    date_ar,
    initials,
    kind_label,
    money,
    percent,
    period_ar,
    progress_width,
    quantity,
    status_class,
    status_label,
    truncate,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

APP_NAME = "Payroll Argentina"
APP_SHORT_NAME = "Payroll"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters.update(
    {
        "money": money,
        "quantity": quantity,
        "percent": percent,
        "progress_width": progress_width,
        "date_ar": date_ar,
        "period_ar": period_ar,
        "status_label": status_label,
        "status_class": status_class,
        "kind_label": kind_label,
        "initials": initials,
        "truncate": truncate,
    }
)
templates.env.globals.update(
    app_name=APP_NAME,
    app_short_name=APP_SHORT_NAME,
    demo_mode=True,
)

router = APIRouter()
web_router = router

DataSource = Annotated[Any, Depends(get_data_source)]

PAYROLL_STATUS_OPTIONS = [
    ("", "Todos los estados"),
    ("draft", "Borrador"),
    ("calculated", "Calculada"),
    ("review", "En revisión"),
    ("approved", "Aprobada"),
    ("closed", "Cerrada"),
]
PROPOSAL_STATUS_OPTIONS = [
    ("", "Todas las propuestas"),
    ("draft", "Borrador"),
    ("in_review", "En revisión"),
    ("approved", "Aprobada"),
    ("rejected", "Rechazada"),
]
RECEIPT_STATUS_OPTIONS = [
    ("", "Todos los estados"),
    ("issued", "Emitidos"),
    ("pending", "Pendientes"),
]
EMPLOYEE_STATUS_OPTIONS = [
    ("", "Todos los estados"),
    ("active", "Activos"),
    ("inactive", "Inactivos"),
]


def _render(
    request: Request,
    template_name: str,
    *,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    base_context: dict[str, Any] = {
        "app_name": APP_NAME,
        "app_short_name": APP_SHORT_NAME,
        "current_year": date.today().year,
        "demo_mode": True,
        "active_nav": "",
    }
    base_context.update(context)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
        status_code=status_code,
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").strip().lower() == "true"


def _not_found(
    request: Request,
    *,
    title: str,
    message: str,
    active_nav: str = "",
) -> HTMLResponse:
    return _render(
        request,
        "not_found.html",
        status_code=404,
        page_title=title,
        message=message,
        active_nav=active_nav,
    )


def _clean_query(value: str | None) -> str:
    return (value or "").strip()[:120]


def _safe_download_name(filename: str, fallback: str = "recibo.pdf") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("._-")
    return stem or fallback


def _attachment_header(filename: str) -> dict[str, str]:
    safe_name = _safe_download_name(filename)
    return {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }


# ---------------------------------------------------------------------------
# Dashboard y salud
# ---------------------------------------------------------------------------


@router.get("/", name="dashboard")
def dashboard(request: Request, data: DataSource) -> HTMLResponse:
    metrics = data.dashboard_metrics()
    return _render(
        request,
        "dashboard.html",
        page_title="Dashboard",
        page_subtitle="Resumen operativo de liquidaciones, empresas y propuestas de IA.",
        active_nav="dashboard",
        metrics=metrics,
        payrolls=data.list_payrolls()[:4],
        proposals=data.list_proposals()[:3],
        companies=data.list_companies()[:3],
        receipts=data.list_receipts()[:3],
    )


@router.get("/salud", name="health_page")
def health_page(request: Request, data: DataSource) -> HTMLResponse:
    pdf_ok, pdf_detail = pdf_backend_status()
    checks = [
        {
            "name": "Aplicación web",
            "status": "ok",
            "detail": "Router Jinja2 + HTMX activo.",
            "hint": "Las páginas se renderizan en el servidor, sin SPA.",
        },
        {
            "name": "Plantillas",
            "status": "ok" if TEMPLATES_DIR.is_dir() else "error",
            "detail": str(TEMPLATES_DIR),
            "hint": "Layout AdminLTE 4 y vistas parciales HTMX.",
        },
        {
            "name": "Exportador PDF",
            "status": "ok" if pdf_ok else "error",
            "detail": pdf_detail,
            "hint": "WeasyPrint se importa de forma diferida al generar un recibo.",
        },
        {
            "name": "Fuente de datos",
            "status": "demo" if data.is_demo else "ok",
            "detail": data.source_name,
            "hint": data.explanation,
        },
        {
            "name": "Base de datos",
            "status": "demo" if data.is_demo else "ok",
            "detail": (
                "Sin sesión SQL en modo demo; el endpoint técnico /health de la "
                "aplicación principal sigue disponible."
                if data.is_demo
                else "Repositorio SQLAlchemy conectado."
            ),
            "hint": "La interfaz consume un repositorio de lectura, nunca reglas de cálculo.",
        },
    ]
    overall = "ok" if all(check["status"] in {"ok", "demo"} for check in checks) else "degraded"
    return _render(
        request,
        "health.html",
        page_title="Estado del sistema",
        page_subtitle="Verificación visual de componentes de la interfaz y del entorno.",
        active_nav="health",
        checks=checks,
        overall=overall,
    )


@router.get("/health/visual", name="health_visual", include_in_schema=False)
def health_visual(request: Request, data: DataSource) -> HTMLResponse:
    """Alias en inglés del health visual; no colisiona con ``GET /health``."""

    return health_page(request, data)


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------


@router.get("/empresas", name="companies_list")
def companies_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    companies = data.list_companies(query)
    context = {
        "companies": companies,
        "query": query,
        "active_nav": "companies",
        "page_title": "Empresas",
        "page_subtitle": "Empleadores, establecimientos y convenios aplicables.",
    }
    if _is_htmx(request):
        return _render(request, "companies/_table.html", **context)
    return _render(request, "companies/list.html", **context)


@router.get("/empresas/{company_id}", name="company_detail")
def company_detail(request: Request, company_id: str, data: DataSource) -> HTMLResponse:
    company = data.get_company(company_id)
    if company is None:
        return _not_found(
            request,
            title="Empresa no encontrada",
            message=f"No existe una empresa con identificador {company_id!r}.",
            active_nav="companies",
        )
    employees = data.employees_for_company(company.id)
    payrolls = data.list_payrolls(company_id=company.id)
    receipts = data.list_receipts(company_id=company.id)
    return _render(
        request,
        "companies/detail.html",
        page_title=company.name,
        page_subtitle=f"{company.activity} · {company.city}, {company.province}",
        active_nav="companies",
        company=company,
        employees=employees,
        payrolls=payrolls,
        receipts=receipts,
    )


# ---------------------------------------------------------------------------
# Empleados
# ---------------------------------------------------------------------------


@router.get("/empleados", name="employees_list")
def employees_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
    company_id: Annotated[str, Query(max_length=80)] = "",
    status: Annotated[str, Query(max_length=30)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    employees = data.list_employees(query=query, company_id=company_id, status=status)
    context = {
        "employees": employees,
        "companies": data.list_companies(),
        "query": query,
        "company_id": company_id,
        "status": status,
        "status_options": EMPLOYEE_STATUS_OPTIONS,
        "active_nav": "employees",
        "page_title": "Empleados",
        "page_subtitle": "Legajos activos, categorías y convenios asignados.",
    }
    if _is_htmx(request):
        return _render(request, "employees/_table.html", **context)
    return _render(request, "employees/list.html", **context)


@router.get("/empleados/{employee_id}", name="employee_detail")
def employee_detail(request: Request, employee_id: str, data: DataSource) -> HTMLResponse:
    employee = data.get_employee(employee_id)
    if employee is None:
        return _not_found(
            request,
            title="Empleado no encontrado",
            message=f"No existe un legajo con identificador {employee_id!r}.",
            active_nav="employees",
        )
    company = data.get_company(employee.company_id)
    receipts = data.list_receipts().copy()
    receipts = [receipt for receipt in receipts if receipt.employee_id == employee.id]
    return _render(
        request,
        "employees/detail.html",
        page_title=employee.name,
        page_subtitle=f"Legajo {employee.file_number} · {employee.company_name}",
        active_nav="employees",
        employee=employee,
        company=company,
        receipts=receipts,
    )


# ---------------------------------------------------------------------------
# Convenios
# ---------------------------------------------------------------------------


@router.get("/convenios", name="agreements_list")
def agreements_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    return _render(
        request,
        "agreements/list.html",
        page_title="Convenios",
        page_subtitle="Repositorio normativo, escalas y propuestas de reglas.",
        active_nav="agreements",
        agreements=data.list_agreements(query),
        query=query,
    )


@router.get("/convenios/{agreement_id}", name="agreement_detail")
def agreement_detail(request: Request, agreement_id: str, data: DataSource) -> HTMLResponse:
    agreement = data.get_agreement(agreement_id)
    if agreement is None:
        return _not_found(
            request,
            title="Convenio no encontrado",
            message=f"No existe un convenio con identificador {agreement_id!r}.",
            active_nav="agreements",
        )
    proposals = [
        proposal for proposal in data.list_proposals() if proposal.agreement == agreement.code
    ]
    return _render(
        request,
        "agreements/detail.html",
        page_title=agreement.code,
        page_subtitle=agreement.name,
        active_nav="agreements",
        agreement=agreement,
        proposals=proposals,
    )


# ---------------------------------------------------------------------------
# Liquidaciones
# ---------------------------------------------------------------------------


@router.get("/liquidaciones", name="payrolls_list")
def payrolls_list(
    request: Request,
    data: DataSource,
    status: Annotated[str, Query(max_length=30)] = "",
    company_id: Annotated[str, Query(max_length=80)] = "",
) -> HTMLResponse:
    payrolls = data.list_payrolls(status=status, company_id=company_id)
    context = {
        "payrolls": payrolls,
        "companies": data.list_companies(),
        "status": status,
        "company_id": company_id,
        "status_options": PAYROLL_STATUS_OPTIONS,
        "active_nav": "payrolls",
        "page_title": "Liquidaciones",
        "page_subtitle": "Borradores, cálculos en revisión y períodos cerrados.",
    }
    if _is_htmx(request):
        return _render(request, "payrolls/_table.html", **context)
    return _render(request, "payrolls/list.html", **context)


@router.get("/liquidaciones/{payroll_id}", name="payroll_detail")
def payroll_detail(request: Request, payroll_id: str, data: DataSource) -> HTMLResponse:
    payroll = data.get_payroll(payroll_id)
    if payroll is None:
        return _not_found(
            request,
            title="Liquidación no encontrada",
            message=f"No existe una liquidación con identificador {payroll_id!r}.",
            active_nav="payrolls",
        )
    receipts = data.list_receipts(company_id=payroll.company_id, period=payroll.period)
    return _render(
        request,
        "payrolls/detail.html",
        page_title=f"Liquidación {payroll.period_label}",
        page_subtitle=f"{payroll.company_name} · {payroll.type}",
        active_nav="payrolls",
        payroll=payroll,
        receipts=receipts,
    )


# ---------------------------------------------------------------------------
# Propuestas de IA
# ---------------------------------------------------------------------------


@router.get("/propuestas-ia", name="proposals_list")
def proposals_list(
    request: Request,
    data: DataSource,
    status: Annotated[str, Query(max_length=30)] = "",
) -> HTMLResponse:
    proposals = data.list_proposals(status=status)
    context = {
        "proposals": proposals,
        "status": status,
        "status_options": PROPOSAL_STATUS_OPTIONS,
        "active_nav": "proposals",
        "page_title": "Propuestas de IA",
        "page_subtitle": "Reglas sugeridas por el analizador, pendientes de revisión humana.",
    }
    if _is_htmx(request):
        return _render(request, "proposals/_table.html", **context)
    return _render(request, "proposals/list.html", **context)


@router.get("/propuestas-ia/{proposal_id}", name="proposal_detail")
def proposal_detail(request: Request, proposal_id: str, data: DataSource) -> HTMLResponse:
    proposal = data.get_proposal(proposal_id)
    if proposal is None:
        return _not_found(
            request,
            title="Propuesta no encontrada",
            message=f"No existe una propuesta con identificador {proposal_id!r}.",
            active_nav="proposals",
        )
    return _render(
        request,
        "proposals/detail.html",
        page_title=proposal.title,
        page_subtitle=f"{proposal.agreement} · {proposal.document}",
        active_nav="proposals",
        proposal=proposal,
        updated=request.query_params.get("updated") == "1",
    )


@router.post("/propuestas-ia/{proposal_id}/estado", name="proposal_update_status")
def proposal_update_status(
    request: Request,
    proposal_id: str,
    data: DataSource,
    status: Annotated[str, Form()],
) -> Response:
    allowed = {"draft", "in_review", "approved", "rejected"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Estado de propuesta no válido.")
    proposal = data.set_proposal_status(proposal_id, status)
    if proposal is None:
        if _is_htmx(request):
            return HTMLResponse(
                '<span class="badge badge--danger">Propuesta no encontrada</span>',
                status_code=404,
            )
        return _not_found(
            request,
            title="Propuesta no encontrada",
            message=f"No existe una propuesta con identificador {proposal_id!r}.",
            active_nav="proposals",
        )
    if _is_htmx(request):
        return _render(request, "proposals/_status.html", proposal=proposal)
    redirect_url = str(request.url_for("proposal_detail", proposal_id=proposal.id)) + "?updated=1"
    return RedirectResponse(url=redirect_url, status_code=303)


# ---------------------------------------------------------------------------
# Recibos
# ---------------------------------------------------------------------------


@router.get("/recibos", name="receipts_list")
def receipts_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
    company_id: Annotated[str, Query(max_length=80)] = "",
    period: Annotated[str, Query(max_length=20)] = "",
    status: Annotated[str, Query(max_length=30)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    receipts = data.list_receipts(
        query=query,
        company_id=company_id,
        period=period,
        status=status,
    )
    context = {
        "receipts": receipts,
        "companies": data.list_companies(),
        "periods": data.receipt_periods(),
        "query": query,
        "company_id": company_id,
        "period": period,
        "status": status,
        "status_options": RECEIPT_STATUS_OPTIONS,
        "active_nav": "receipts",
        "page_title": "Recibos de sueldo",
        "page_subtitle": "Emisión individual, vista previa y descarga masiva en PDF.",
    }
    if _is_htmx(request):
        return _render(request, "receipts/_table.html", **context)
    return _render(request, "receipts/list.html", **context)


@router.get("/recibos/lote.zip", name="receipts_zip")
def receipts_zip(
    data: DataSource,
    company_id: Annotated[str, Query(max_length=80)] = "",
    period: Annotated[str, Query(max_length=20)] = "",
) -> Response:
    receipts = data.list_receipts(company_id=company_id, period=period)
    if not receipts:
        raise HTTPException(status_code=404, detail="No hay recibos para los filtros indicados.")
    try:
        archive = render_receipts_zip(receipt.to_pdf_context() for receipt in receipts)
    except ReceiptContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    suffix = period or "todos"
    return Response(
        content=archive,
        media_type="application/zip",
        headers=_attachment_header(f"recibos-{suffix}.zip"),
    )


@router.get("/recibos/{receipt_id}", name="receipt_detail")
def receipt_detail(request: Request, receipt_id: str, data: DataSource) -> HTMLResponse:
    receipt = data.get_receipt(receipt_id)
    if receipt is None:
        return _not_found(
            request,
            title="Recibo no encontrado",
            message=f"No existe un recibo con identificador {receipt_id!r}.",
            active_nav="receipts",
        )
    return _render(
        request,
        "receipts/detail.html",
        page_title=f"Recibo {receipt.number}",
        page_subtitle=f"{receipt.employee.get('name', '')} · {receipt.period_label}",
        active_nav="receipts",
        receipt=receipt,
        preview_url=request.url_for("receipt_preview", receipt_id=receipt.id),
        pdf_url=request.url_for("receipt_pdf", receipt_id=receipt.id),
    )


@router.get("/recibos/{receipt_id}/vista", name="receipt_preview")
def receipt_preview(receipt_id: str, data: DataSource) -> HTMLResponse:
    receipt = data.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Recibo no encontrado.")
    try:
        html = render_receipt_html(receipt.to_pdf_context())
    except ReceiptContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HTMLResponse(
        content=html,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self' data:"
            ),
        },
    )


@router.get("/recibos/{receipt_id}/pdf", name="receipt_pdf")
def receipt_pdf(receipt_id: str, data: DataSource) -> Response:
    receipt = data.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Recibo no encontrado.")
    try:
        pdf = render_receipt_pdf(receipt.to_pdf_context())
    except ReceiptContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=_attachment_header(f"recibo-{receipt.number}.pdf"),
    )


# ---------------------------------------------------------------------------
# Recursos locales (sin CDN obligatorio)
# ---------------------------------------------------------------------------


@router.get("/static/app.css", name="web_css", include_in_schema=False)
def web_css() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "css" / "app.css",
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/static/app.js", name="web_js", include_in_schema=False)
def web_js() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "js" / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


__all__ = ["router", "templates", "web_router"]
