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

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.imports import _read_upload, import_novelties
from app.api.payroll_runs import (
    approve_payroll_run,
    calculate_run,
    create_payroll_run,
    export_payroll_results,
    reopen_payroll_run,
)
from app.api.reports import export_f931_workbook
from app.api.schemas import PayrollRunInput
from app.config import Settings, get_settings
from app.database.models import Employee, PayrollResult, PayrollRun, PayrollTrace, User
from app.database.session import get_db
from app.exporters.pdf.receipts import (
    PdfRendererUnavailable,
    ReceiptContextError,
    ReceiptError,
    pdf_backend_status,
    render_receipt_html,
    render_receipt_pdf,
    render_receipts_zip,
)
from app.web.auth import (
    WebUser,
    authenticate_web_user,
    clear_web_session,
    create_csrf_token,
    csrf_token_for,
    enforce_csrf,
    require_web_user,
    resolve_web_user,
    revoke_demo_session,
    safe_next_url,
    set_csrf_cookie,
    start_web_session,
)
from app.web.dependencies import get_data_source, scope_data_source
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
protected_router = APIRouter(dependencies=[Depends(require_web_user)])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_db)]
WebUserDep = Annotated[WebUser, Depends(require_web_user)]
PublicDataSource = Annotated[Any, Depends(get_data_source)]


def _request_data_source(
    request: Request,
    user: WebUserDep,
    db: SessionDep,
    data: PublicDataSource,
) -> Any:
    """Scope the configured source to the authenticated user's organization.

    ``user`` is deliberately the first dependency so the source is resolved
    only after authentication; the scope itself is then derived from the user,
    never from a client-supplied parameter.  Demo sources are returned
    untouched.
    """

    if user.is_demo or bool(getattr(data, "is_demo", False)):
        request.state.payroll_data_source = data
        return data
    organization_id = db.scalar(
        select(User.organization_id).where(User.id == user.id)
    )
    if organization_id is None:
        # Fail closed: never expose an unscoped source when the organization
        # cannot be resolved.
        scoped = scope_data_source(data, -1)
        request.state.payroll_data_source = scoped
        return scoped
    scoped = scope_data_source(data, organization_id)
    request.state.payroll_data_source = scoped
    return scoped


DataSource = Annotated[Any, Depends(_request_data_source)]

PAYROLL_STATUS_OPTIONS = [
    ("", "Todos los estados"),
    ("draft", "Borrador"),
    ("calculated", "Calculada"),
    ("review", "En revisión"),
    ("error", "Con errores"),
    ("approved", "Aprobada"),
    ("closed", "Cerrada"),
    ("annulled", "Anulada"),
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

# B-53: tope de filas por página en las listas HTML (la API usa limit ≤ 100).
WEB_PAGE_SIZE = 50


def _page_offset(page: int) -> tuple[int, int]:
    safe_page = max(int(page or 1), 1)
    return WEB_PAGE_SIZE, (safe_page - 1) * WEB_PAGE_SIZE


def _receipts_error_redirect(
    request: Request,
    *,
    company_id: str = "",
    period: str = "",
    payroll_id: str = "",
    q: str = "",
    status: str = "",
    error: str,
) -> RedirectResponse:
    params = {key: value for key, value in (("company_id", company_id), ("period", period), ("payroll_id", payroll_id), ("q", q), ("status", status)) if value}
    params["error"] = error
    return RedirectResponse(
        url=f"{request.url_for('receipts_list')}?{urlencode(params)}",
        status_code=303,
    )


def _render(
    request: Request,
    template_name: str,
    *,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    data = get_data_source(request)
    current_user = getattr(request.state, "web_user", None)
    settings = getattr(request.state, "web_settings", None)
    csrf_token = ""
    if (
        isinstance(current_user, WebUser)
        and isinstance(settings, Settings)
        and settings.web_auth_enabled
    ):
        csrf_token = csrf_token_for(request, settings, current_user.id)

    base_context: dict[str, Any] = {
        "app_name": APP_NAME,
        "app_short_name": APP_SHORT_NAME,
        "current_year": date.today().year,
        "current_user": current_user,
        "csrf_token": csrf_token,
        "demo_mode": bool(getattr(data, "is_demo", False)),
        "data_source_name": getattr(data, "source_name", "Fuente de datos"),
        "data_source_explanation": getattr(data, "explanation", ""),
        "active_nav": "",
    }
    base_context.update(context)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
        status_code=status_code,
    )
    if csrf_token and isinstance(settings, Settings):
        set_csrf_cookie(response, csrf_token, settings)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "private, no-store")
    return response


def _render_login(
    request: Request,
    settings: Settings,
    *,
    email: str = "",
    error: str | None = None,
    next_url: str = "/",
    status_code: int = 200,
    demo_mode: bool = False,
) -> HTMLResponse:
    csrf_token = csrf_token_for(request, settings, None)
    response = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_name": APP_NAME,
            "app_short_name": APP_SHORT_NAME,
            "current_year": date.today().year,
            "csrf_token": csrf_token,
            "email": email,
            "error": error,
            "next_url": next_url,
            "demo_mode": demo_mode,
        },
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token, settings)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store")
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
# Autenticación
# ---------------------------------------------------------------------------


@router.get("/login", name="login_page")
def login_page(
    request: Request,
    settings: SettingsDep,
    db: SessionDep,
    data: PublicDataSource,
) -> Response:
    next_url = safe_next_url(request.query_params.get("next"))
    if not settings.web_auth_enabled:
        return RedirectResponse(url=next_url, status_code=303)
    if resolve_web_user(request, db, settings, data) is not None:
        return RedirectResponse(url=next_url, status_code=303)
    return _render_login(
        request, settings, next_url=next_url, demo_mode=bool(getattr(data, "is_demo", False))
    )


@router.post("/login", name="login_submit")
def login_submit(
    request: Request,
    settings: SettingsDep,
    db: SessionDep,
    data: PublicDataSource,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    next_url = safe_next_url(next or request.query_params.get("next"))
    if not settings.web_auth_enabled:
        return RedirectResponse(url=next_url, status_code=303)
    enforce_csrf(request, csrf_token, settings, None)
    user = authenticate_web_user(
        email=email[:254],
        password=password,
        db=db,
        settings=settings,
        data=data,
    )
    if user is None:
        return _render_login(
            request,
            settings,
            email=email.strip()[:254],
            error="Credenciales inválidas. Revisá el email y la contraseña.",
            next_url=next_url,
            status_code=401,
        )
    response = RedirectResponse(url=next_url, status_code=303)
    start_web_session(response, user, settings)
    set_csrf_cookie(response, create_csrf_token(settings.secret_key, user.id), settings)
    return response


@protected_router.post("/logout", name="logout")
def logout(
    request: Request,
    user: WebUserDep,
    settings: SettingsDep,
    db: SessionDep,
    data: PublicDataSource,
    csrf_token: Annotated[str, Form()] = "",
) -> Response:
    enforce_csrf(request, csrf_token, settings, user.id)
    # V2-01: invalidar la sesión en el servidor para que la cookie copiada
    # deje de aceptarse. En SQL se rota ``session_version`` (igual que el
    # logout de la API); en demo se revoca el token en memoria.
    if user.is_demo or bool(getattr(data, "is_demo", False)):
        revoke_demo_session(request.cookies.get(settings.session_cookie))
    else:
        row = db.get(User, user.id)
        if row is not None:
            row.session_version += 1
            db.add(row)
            db.commit()
    response = RedirectResponse(url=request.url_for("login_page").path, status_code=303)
    clear_web_session(response, settings)
    return response


# ---------------------------------------------------------------------------
# Dashboard y salud
# ---------------------------------------------------------------------------


@protected_router.get("/", name="dashboard")
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
def health_page(
    request: Request,
    data: PublicDataSource,
    db: SessionDep,
) -> HTMLResponse:
    pdf_ok, pdf_detail = pdf_backend_status()
    if data.is_demo:
        db_status, db_detail = (
            "demo",
            "Sin sesión SQL en modo demo; el endpoint técnico /health de la "
            "aplicación principal sigue disponible.",
        )
    else:
        # PW-1: probar la conexión real en modo SQL en vez de declararla.
        try:
            db.scalar(select(func.count()).select_from(User))
            db_status, db_detail = "ok", "Base de datos SQL conectada; tabla users legible."
        except Exception:
            db_status, db_detail = (
                "error",
                "Base de datos SQL no disponible; revise DATABASE_URL y migraciones.",
            )
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
            "status": db_status,
            "detail": db_detail,
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
def health_visual(request: Request, data: PublicDataSource, db: SessionDep) -> HTMLResponse:
    """Alias en inglés del health visual; no colisiona con ``GET /health``."""

    return health_page(request, data, db)


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------


@protected_router.get("/empresas", name="companies_list")
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


@protected_router.get("/empresas/{company_id}", name="company_detail")
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


@protected_router.get("/empleados", name="employees_list")
def employees_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
    company_id: Annotated[str, Query(max_length=80)] = "",
    status: Annotated[str, Query(max_length=30)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    query = _clean_query(q)
    limit, offset = _page_offset(page)
    employees = data.list_employees(
        query=query, company_id=company_id, status=status, limit=limit, offset=offset
    )
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


@protected_router.get("/empleados/{employee_id}", name="employee_detail")
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


@protected_router.get("/convenios", name="agreements_list")
def agreements_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    context = {
        "agreements": data.list_agreements(query),
        "query": query,
        "active_nav": "agreements",
        "page_title": "Convenios",
        "page_subtitle": "Repositorio normativo, escalas y propuestas de reglas.",
    }
    if _is_htmx(request):
        return _render(request, "agreements/_table.html", **context)
    return _render(request, "agreements/list.html", **context)


@protected_router.get("/convenios/{agreement_id}", name="agreement_detail")
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


@protected_router.get("/liquidaciones", name="payrolls_list")
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



def _sql_user(db: Session, user: WebUser, data: Any, roles: set[str]) -> User:
    if user.is_demo or getattr(data, "is_demo", False):
        raise HTTPException(status_code=403, detail="El modo demo es de solo lectura.")
    row = db.get(User, user.id)
    if row is None or not row.active or row.role not in roles:
        raise HTTPException(status_code=403, detail="Permiso insuficiente.")
    return row


def _run(db: Session, user: User, run_id: int) -> PayrollRun:
    row = db.scalar(select(PayrollRun).where(
        PayrollRun.id == run_id, PayrollRun.organization_id == user.organization_id
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    return row


def _payroll_redirect(request: Request, run_id: int | None = None, **params: str) -> RedirectResponse:
    url = str(request.url_for("payroll_detail", payroll_id=run_id)) if run_id else str(request.url_for("payrolls_list"))
    if params:
        url += "?" + urlencode(params)
    return RedirectResponse(url, status_code=303)


@protected_router.post("/liquidaciones", name="payroll_create")
def payroll_create(
    request: Request, data: DataSource, user: WebUserDep, db: SessionDep, settings: SettingsDep,
    company_id: Annotated[str, Form()], code: Annotated[str, Form()],
    period_start: Annotated[str, Form()], period_end: Annotated[str, Form()],
    run_type: Annotated[str, Form()], csrf_token: Annotated[str, Form()] = "",
) -> Response:
    enforce_csrf(request, csrf_token, settings, user.id)
    actor = _sql_user(db, user, data, {"admin", "editor"})
    try:
        payload = PayrollRunInput(company_id=company_id, code=code.strip(), period_start=period_start,
                                  period_end=period_end, run_type=run_type)
        run = create_payroll_run(payload, db=db, user=actor)
    except (ValidationError, HTTPException) as exc:
        db.rollback()
        return _payroll_redirect(request, error=_error_message(exc))
    return _payroll_redirect(request, run.id, notice="Liquidación creada. Cargue novedades y calcule.")


def _error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)[:300]
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())[:300]
    return str(exc)[:300]


@protected_router.post("/liquidaciones/{run_id}/accion", name="payroll_action")
def payroll_action(
    request: Request, run_id: int, data: DataSource, user: WebUserDep, db: SessionDep,
    settings: SettingsDep, action: Annotated[str, Form()], csrf_token: Annotated[str, Form()] = "",
) -> Response:
    enforce_csrf(request, csrf_token, settings, user.id)
    actor = _sql_user(db, user, data, {"admin"} if action in {"approve", "reopen"} else {"admin", "editor"})
    run = _run(db, actor, run_id)
    try:
        if action == "calculate":
            calculate_run(run_id, include_items=False, results_limit=50, results_offset=0,
                          allow_unconsumed_novelties=False, db=db, user=actor)
            notice = "Cálculo terminado. Revise los resultados y alertas."
        elif action == "reopen":
            reopen_payroll_run(run_id, db=db, user=actor)
            notice = "Liquidación reabierta. Puede modificar novedades y recalcular."
        elif action == "approve":
            count = db.scalar(select(func.count(PayrollResult.id)).where(PayrollResult.payroll_run_id == run.id))
            if run.status not in {"CALCULATED", "IN_REVIEW"} or not count:
                raise HTTPException(status_code=409, detail="Solo se aprueban liquidaciones calculadas con resultados y sin errores.")
            approve_payroll_run(run_id, db=db, user=actor)
            notice = "Liquidación aprobada."
        else:
            raise HTTPException(status_code=400, detail="Acción no válida.")
    except HTTPException as exc:
        db.rollback()
        return _payroll_redirect(request, run_id, error=_error_message(exc))
    return _payroll_redirect(request, run_id, notice=notice)


@protected_router.post("/liquidaciones/{run_id}/novedades", name="payroll_novelties")
def payroll_novelties(
    request: Request, run_id: int, data: DataSource, user: WebUserDep, db: SessionDep,
    settings: SettingsDep, file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str, Form()] = "", confirmation: Annotated[str, Form()] = "",
) -> Response:
    enforce_csrf(request, csrf_token, settings, user.id)
    actor = _sql_user(db, user, data, {"admin", "editor"})
    run = _run(db, actor, run_id)
    if run.status != "DRAFT":
        return _payroll_redirect(request, run_id, error="Reabra la liquidación antes de importar novedades.")
    try:
        content, filename = _read_upload(file)
        preview = import_novelties(file=file, dry_run=True, company_id=run.company_id, db=db, user=actor)
        period = run.period_end.strftime("%Y%m")
        if any(row["periodo"] != period for row in preview["valid_rows"]):
            raise HTTPException(status_code=400, detail=f"Todas las novedades deben corresponder al período {period}.")
        serializer = URLSafeTimedSerializer(settings.secret_key, salt="payroll-web-import")
        proof = {"run": run.id, "user": actor.id, "digest": hashlib.sha256(content).hexdigest(), "suffix": Path(filename).suffix.lower()}
        if confirmation:
            try:
                signed = serializer.loads(confirmation, max_age=3600)
            except BadSignature as exc:
                raise HTTPException(status_code=400, detail="La confirmación venció. Revise el archivo nuevamente.") from exc
            if signed != proof:
                raise HTTPException(status_code=400, detail="El archivo no coincide con el revisado.")
            result = import_novelties(file=file, dry_run=False, company_id=run.company_id, db=db, user=actor)
            problems = result.get("errors", []) + result.get("duplicates", [])
            message = f"Importación terminada: {result.get('created', 0)} creadas; {len(problems)} errores o duplicados."
            if problems:
                message += " " + "; ".join(f"Fila {item.get('row', '?')}: {item.get('message', '')}" for item in problems[:3])[:200]
            return _payroll_redirect(request, run_id, notice=message)
        token = serializer.dumps(proof)
    except HTTPException as exc:
        db.rollback()
        return _payroll_redirect(request, run_id, error=_error_message(exc))
    return _render(request, "payrolls/import_preview.html", page_title="Revisar novedades",
                   page_subtitle=f"Liquidación {run.code}", active_nav="payrolls", run=run,
                   preview=preview, confirmation=token, filename=filename)


@protected_router.get("/liquidaciones/{run_id}/descargar/{kind}", name="payroll_download")
def payroll_download(run_id: int, kind: str, data: DataSource, user: WebUserDep, db: SessionDep) -> Response:
    actor = _sql_user(db, user, data, {"admin", "editor", "viewer"})
    _run(db, actor, run_id)
    if kind == "resultados":
        return export_payroll_results(run_id, format="csv", db=db, user=actor)
    if kind == "f931":
        return export_f931_workbook(run_id, db=db, user=actor)
    raise HTTPException(status_code=404, detail="Descarga no encontrada.")



@protected_router.get("/liquidaciones/{payroll_id}", name="payroll_detail")
def payroll_detail(request: Request, payroll_id: str, data: DataSource, user: WebUserDep, db: SessionDep) -> HTMLResponse:
    payroll = data.get_payroll(payroll_id)
    if payroll is None:
        return _not_found(
            request,
            title="Liquidación no encontrada",
            message=f"No existe una liquidación con identificador {payroll_id!r}.",
            active_nav="payrolls",
        )
    receipts = data.list_receipts(payroll_id=payroll.id)
    traces: list[Any] = []
    if not user.is_demo and not getattr(data, "is_demo", False) and payroll_id.isdigit():
        actor = _sql_user(db, user, data, {"admin", "editor", "viewer"})
        run = _run(db, actor, int(payroll_id))
        traces = list(db.execute(select(PayrollTrace, Employee).outerjoin(
            Employee, Employee.id == PayrollTrace.employee_id
        ).where(PayrollTrace.payroll_run_id == run.id).order_by(PayrollTrace.id)).all())
    approval_blocked = any(
        alert.get("type") in {"settlement_missing_rules", "settlement_incomplete"}
        for trace, _employee in traces if trace.event == "CALCULATION_REVIEW"
        for alert in trace.detail.get("warnings", [])
    )
    return _render(
        request,
        "payrolls/detail.html",
        page_title=f"Liquidación {payroll.period_label}",
        page_subtitle=f"{payroll.company_name} · {payroll.type}",
        active_nav="payrolls",
        payroll=payroll,
        receipts=receipts,
        traces=traces,
        approval_blocked=approval_blocked,
    )


# ---------------------------------------------------------------------------
# Propuestas de IA
# ---------------------------------------------------------------------------


@protected_router.get("/propuestas-ia", name="proposals_list")
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


@protected_router.get("/propuestas-ia/{proposal_id}", name="proposal_detail")
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


@protected_router.post("/propuestas-ia/{proposal_id}/estado", name="proposal_update_status")
def proposal_update_status(
    request: Request,
    proposal_id: str,
    data: DataSource,
    user: WebUserDep,
    settings: SettingsDep,
    status: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
) -> Response:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Permiso insuficiente.")
    enforce_csrf(request, csrf_token, settings, user.id)
    allowed = {"draft", "in_review", "approved", "rejected"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Estado de propuesta no válido.")
    proposal = data.set_proposal_status(proposal_id, status, user_id=user.id)
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


@protected_router.get("/recibos", name="receipts_list")
def receipts_list(
    request: Request,
    data: DataSource,
    q: Annotated[str, Query(max_length=120)] = "",
    company_id: Annotated[str, Query(max_length=80)] = "",
    period: Annotated[str, Query(max_length=20)] = "",
    status: Annotated[str, Query(max_length=30)] = "",
    payroll_id: Annotated[str, Query(max_length=80)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    error: Annotated[str, Query(max_length=200)] = "",
) -> HTMLResponse:
    query = _clean_query(q)
    limit, offset = _page_offset(page)
    receipts = data.list_receipts(
        query=query,
        company_id=company_id,
        period=period,
        status=status,
        payroll_id=payroll_id,
        limit=limit,
        offset=offset,
    )
    context = {
        "receipts": receipts,
        "companies": data.list_companies(),
        "periods": data.receipt_periods(),
        "query": query,
        "company_id": company_id,
        "period": period,
        "status": status,
        "payroll_id": payroll_id,
        "error": _clean_query(error),
        "status_options": RECEIPT_STATUS_OPTIONS,
        "active_nav": "receipts",
        "page_title": "Recibos de sueldo",
        "page_subtitle": "Emisión individual, vista previa y descarga masiva en PDF.",
    }
    if _is_htmx(request):
        return _render(request, "receipts/_table.html", **context)
    return _render(request, "receipts/list.html", **context)


@protected_router.get("/recibos/lote.zip", name="receipts_zip")
def receipts_zip(
    request: Request,
    data: DataSource,
    company_id: Annotated[str, Query(max_length=80)] = "",
    period: Annotated[str, Query(max_length=20)] = "",
    payroll_id: Annotated[str, Query(max_length=80)] = "",
    q: Annotated[str, Query(max_length=120)] = "",
    status: Annotated[str, Query(max_length=30)] = "",
) -> Response:
    receipts = data.list_receipts(company_id=company_id, period=period, payroll_id=payroll_id, query=_clean_query(q), status=status)
    if not receipts:
        return _receipts_error_redirect(
            request,
            company_id=company_id,
            period=period,
            payroll_id=payroll_id,
            q=q, status=status,
            error="No hay recibos para los filtros indicados.",
        )
    try:
        archive = render_receipts_zip(receipt.to_pdf_context() for receipt in receipts)
    except (ReceiptError, PdfRendererUnavailable) as exc:
        return _receipts_error_redirect(
            request, company_id=company_id, period=period, payroll_id=payroll_id, q=q, status=status, error=str(exc)[:200]
        )
    suffix = period or "todos"
    return Response(
        content=archive,
        media_type="application/zip",
        headers=_attachment_header(f"recibos-{suffix}.zip"),
    )


@protected_router.get("/recibos/{receipt_id}", name="receipt_detail")
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


@protected_router.get("/recibos/{receipt_id}/vista", name="receipt_preview")
def receipt_preview(request: Request, receipt_id: str, data: DataSource) -> HTMLResponse:
    receipt = data.get_receipt(receipt_id)
    if receipt is None:
        return _not_found(
            request,
            title="Recibo no encontrado",
            message=f"No existe un recibo con identificador {receipt_id!r}.",
            active_nav="receipts",
        )
    try:
        html = render_receipt_html(receipt.to_pdf_context())
    except ReceiptContextError as exc:
        return _not_found(
            request,
            title="Recibo no disponible",
            message=str(exc),
            active_nav="receipts",
        )
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


@protected_router.get("/recibos/{receipt_id}/pdf", name="receipt_pdf")
def receipt_pdf(request: Request, receipt_id: str, data: DataSource) -> Response:
    receipt = data.get_receipt(receipt_id)
    if receipt is None:
        return _receipts_error_redirect(request, error="Recibo no encontrado.")
    try:
        pdf = render_receipt_pdf(receipt.to_pdf_context())
    except (ReceiptError, PdfRendererUnavailable) as exc:
        return _receipts_error_redirect(request, error=str(exc)[:200])
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


router.include_router(protected_router)

# Keep the whole web UI available when mounted under a prefix or in tests.
from app.web.configuration import router as configuration_router  # noqa: E402
from app.web.operations import router as operations_router  # noqa: E402

router.include_router(configuration_router)
router.include_router(operations_router)


__all__ = ["router", "templates", "web_router"]
