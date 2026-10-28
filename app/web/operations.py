"""Human-reviewed settlement inputs, internal corrections and legacy repair."""
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import or_, select

from app.api.imports import RepairNoveltyInput, repair_novelty_company
from app.api.payroll_runs import AnnulInput, ReplaceInput, annul_payroll_run, replace_payroll_run
from app.api.settlements import save_settlement_inputs
from app.database.models import (
    Company,
    Employee,
    EmploymentContract,
    PayrollNovelty,
    PayrollSettlementInput,
)
from app.services.settlement_inputs import SettlementInputs
from app.web.auth import enforce_csrf
from app.web.routes import (
    DataSource,
    SessionDep,
    SettingsDep,
    WebUserDep,
    _error_message,
    _payroll_redirect,
    _render,
    _run,
    _sql_user,
)

router: APIRouter = APIRouter()

# The field names are the typed API contract; labels remain accountant-facing.
INPUT_FIELDS = (
    ("worked_days", "Días de sueldo pendientes"),
    ("worked_base_salary", "Base mensual de los días pendientes"),
    ("vacation_days", "Días de vacaciones a liquidar"),
    ("vacation_base_salary", "Base de vacaciones con remuneración variable revisada"),
    ("sac_excluded_days", "Días sin devengamiento de SAC en el semestre (0 si no hay)"),
    ("indemnity_base_salary", "Base indemnizatoria revisada"),
    ("indemnity_cap", "Tope indemnizatorio aplicable"),
    ("notice_base_salary", "Base mensual del preaviso"),
    ("preaviso_months", "Meses de preaviso pendientes"),
    ("integration_days", "Días de integración del mes"),
)


@router.get("/liquidaciones/{run_id}/operaciones", name="payroll_operations")
def payroll_operations(request: Request, run_id: int, data: DataSource, user: WebUserDep, db: SessionDep):
    actor = _sql_user(db, user, data, {"admin", "editor", "viewer"})
    run = _run(db, actor, run_id)
    employees = db.scalars(select(Employee).join(EmploymentContract).where(
        Employee.organization_id == actor.organization_id,
        EmploymentContract.company_id == run.company_id,
        EmploymentContract.valid_from <= run.period_end,
        or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= run.period_start),
    ).order_by(Employee.employee_code)).unique().all()
    values = {row.employee_id: row.values for row in db.scalars(select(PayrollSettlementInput).where(
        PayrollSettlementInput.payroll_run_id == run.id,
    )).all()}
    return _render(request, "payrolls/operations.html", page_title=f"Preparar {run.code}",
                   active_nav="payrolls", run=run, employees=employees, values=values,
                   input_fields=INPUT_FIELDS)


@router.post("/liquidaciones/{run_id}/operaciones/{action}", name="payroll_operation")
async def payroll_operation(request: Request, run_id: int, action: str, data: DataSource,
                            user: WebUserDep, db: SessionDep, settings: SettingsDep):
    form = await request.form()
    enforce_csrf(request, str(form.get("csrf_token", "")), settings, user.id)
    actor = _sql_user(db, user, data, {"admin", "editor"} if action == "inputs" else {"admin"})
    _run(db, actor, run_id)
    try:
        if action == "annul":
            annul_payroll_run(run_id, AnnulInput(reason=form.get("reason")), db=db, user=actor)
            return _payroll_redirect(request, run_id, notice="Liquidación anulada internamente. Se conserva su historial.")
        if action == "replace":
            replacement = replace_payroll_run(run_id, ReplaceInput(reason=form.get("reason"), code=form.get("code")), db=db, user=actor)
            return _payroll_redirect(request, replacement.id, notice="Reemplazo interno creado. Revise los datos y calcule la liquidación completa.")
        if action == "inputs":
            payload: dict[str, Any] = {name: form[name] for name, _ in INPUT_FIELDS if form.get(name) not in (None, "")}
            for name in ("sac_excluded_days", "integration_days"):
                if name in payload:
                    payload[name] = int(payload[name])
            if form.get("cause"):
                payload["cause"] = form["cause"]
            for name in ("probation", "without_notice", "other_entitlements_reviewed"):
                if form.get(name) not in (None, ""):
                    if form[name] not in {"true", "false"}:
                        raise ValueError(f"{name}: seleccione Sí o No.")
                    payload[name] = form[name] == "true"
            save_settlement_inputs(db, run_id, int(str(form.get("employee_id", ""))), SettlementInputs(**payload), actor)
            return _payroll_redirect(request, run_id, notice="Insumos guardados. Calcule y revise las trazas antes de aprobar.")
        raise HTTPException(status_code=400, detail="Operación no válida.")
    except (HTTPException, ValidationError, ValueError) as exc:
        db.rollback()
        return _payroll_redirect(request, run_id, error=_error_message(exc))


@router.get("/novedades/reparar", name="novelty_repairs")
def novelty_repairs(request: Request, data: DataSource, user: WebUserDep, db: SessionDep):
    actor = _sql_user(db, user, data, {"admin"})
    rows = db.execute(select(PayrollNovelty, Employee).join(Employee).where(
        PayrollNovelty.organization_id == actor.organization_id,
        PayrollNovelty.company_id.is_(None), Employee.organization_id == actor.organization_id,
    ).order_by(PayrollNovelty.id).limit(100)).all()
    companies = db.scalars(select(Company).where(Company.organization_id == actor.organization_id).order_by(Company.legal_name)).all()
    return _render(request, "payrolls/repairs.html", page_title="Asignar empresa a novedades históricas",
                   active_nav="payrolls", rows=rows, companies=companies)


@router.post("/novedades/{novelty_id}/reparar", name="novelty_repair")
async def novelty_repair(request: Request, novelty_id: int, data: DataSource,
                         user: WebUserDep, db: SessionDep, settings: SettingsDep):
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    form = await request.form()
    enforce_csrf(request, str(form.get("csrf_token", "")), settings, user.id)
    actor = _sql_user(db, user, data, {"admin"})
    try:
        repair_novelty_company(novelty_id, RepairNoveltyInput(
            company_id=form.get("company_id"), reason=form.get("reason")), db=db, user=actor)
        params = {"notice": "Empresa asignada. Recalcule las liquidaciones afectadas."}
    except (HTTPException, ValidationError) as exc:
        db.rollback()
        params = {"error": _error_message(exc)}
    return RedirectResponse(str(request.url_for("novelty_repairs")) + "?" + urlencode(params), status_code=303)
