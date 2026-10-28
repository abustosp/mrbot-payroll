# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import PayrollRunInput, PayrollRunRead
from app.auth.dependencies import require_role, require_user
from app.database.models import (
    AuditLog,
    Company,
    Employee,
    PayrollApproval,
    PayrollResult,
    PayrollRun,
    PayrollTrace,
    User,
)
from app.database.session import get_db
from app.exporters.tabular import normalize_format, table_response
from app.services.payroll_calculation import (
    PayrollRunStateError,
    _clear_previous_results,
    calculate_payroll_run,
)

router = APIRouter(prefix="/payroll-runs", tags=["payroll-runs"])

RUN_EXPORT_COLUMNS = [
    "id", "code", "company_id", "period_start", "period_end", "run_type",
    "status", "ruleset_id",
]

RESULT_EXPORT_COLUMNS = [
    "id", "employee_id", "employee_code", "remunerative", "non_remunerative",
    "deductions", "contributions", "gross", "net", "employer_cost",
]


@router.get("")
def list_payroll_runs(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    statement = select(PayrollRun).where(
        PayrollRun.organization_id == user.organization_id
    ).order_by(PayrollRun.id)
    result = page(db, statement, limit, offset)
    result["items"] = [PayrollRunRead.model_validate(item) for item in result["items"]]
    return result


@router.get("/export")
def export_payroll_runs(
    format: str = Query(default="csv", max_length=10),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Descarga todas las liquidaciones de la organización en csv, xlsx o json."""

    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = db.scalars(
        select(PayrollRun).where(
            PayrollRun.organization_id == user.organization_id
        ).order_by(PayrollRun.id)
    ).all()
    rows = [PayrollRunRead.model_validate(item).model_dump(mode="json") for item in items]
    return table_response(rows, RUN_EXPORT_COLUMNS, "liquidaciones", fmt)


@router.get("/{run_id}/results/export")
def export_payroll_results(
    run_id: int,
    format: str = Query(default="csv", max_length=10),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Descarga los resultados calculados de una liquidación en csv, xlsx o json."""

    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run = get_scoped(db, PayrollRun, run_id, user.organization_id)
    results = db.scalars(
        select(PayrollResult).where(
            PayrollResult.payroll_run_id == run.id
        ).order_by(PayrollResult.id)
    ).all()
    codes = dict(
        db.execute(
            select(Employee.id, Employee.employee_code).where(
                Employee.organization_id == user.organization_id
            )
        ).all()
    )
    rows = [
        {
            "id": result.id,
            "employee_id": result.employee_id,
            "employee_code": codes.get(result.employee_id, ""),
            "remunerative": str(result.remunerative),
            "non_remunerative": str(result.non_remunerative),
            "deductions": str(result.deductions),
            "contributions": str(result.contributions),
            "gross": str(result.gross),
            "net": str(result.net),
            "employer_cost": str(result.employer_cost),
        }
        for result in results
    ]
    return table_response(rows, RESULT_EXPORT_COLUMNS, f"liquidacion-{run.code}", fmt)


@router.post("", response_model=PayrollRunRead, status_code=status.HTTP_201_CREATED)
def create_payroll_run(
    payload: PayrollRunInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    company = db.scalar(
        select(Company).where(
            Company.id == payload.company_id,
            Company.organization_id == user.organization_id,
        ).with_for_update()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    # Share the import lock, including SQLite where FOR UPDATE is ignored.
    db.execute(update(Company).where(Company.id == company.id).values(active=Company.active))
    row = PayrollRun(
        organization_id=user.organization_id,
        created_by=user.id,
        status="DRAFT",
        **payload.model_dump(),
    )
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.get("/{run_id}", response_model=PayrollRunRead)
def get_payroll_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return get_scoped(db, PayrollRun, run_id, user.organization_id)


@router.post("/{run_id}/calculate")
def calculate_run(
    run_id: int,
    include_items: bool = Query(
        default=True, description="Incluir el detalle por empleado en la respuesta.",
    ),
    results_limit: int | None = Query(
        default=50, ge=1, le=500, description="Ventana de detalle paginado.",
    ),
    results_offset: int = Query(default=0, ge=0),
    allow_unconsumed_novelties: bool = Query(
        default=False,
        description="Aceptar novedades no consumidas como aviso en vez de error.",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Calculate the run. B-36: the summary is always complete; the detail is
    paginated with ``include_items``/``results_limit``/``results_offset``."""

    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    try:
        result = calculate_payroll_run(
            db,
            row,
            include_items=include_items,
            results_limit=results_limit,
            results_offset=results_offset,
            allow_unconsumed_novelties=allow_unconsumed_novelties,
        )
    except PayrollRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    commit_or_conflict(db)
    return result


@router.put("/{run_id}", response_model=PayrollRunRead)
def update_payroll_run(
    run_id: int, payload: PayrollRunInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Solo se editan liquidaciones en borrador")
    company = db.scalar(
        select(Company).where(
            Company.id == payload.company_id,
            Company.organization_id == user.organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    claimed = db.execute(
        update(PayrollRun)
        .where(PayrollRun.id == row.id, PayrollRun.status == "DRAFT")
        .values(**payload.model_dump())
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Solo se editan liquidaciones en borrador")
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payroll_run(
    run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Solo se eliminan liquidaciones en borrador")
    claimed = db.execute(
        delete(PayrollRun).where(PayrollRun.id == row.id, PayrollRun.status == "DRAFT")
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Solo se eliminan liquidaciones en borrador")
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{run_id}/approve", response_model=PayrollRunRead)
def approve_payroll_run(
    run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    claimed = db.execute(
        update(PayrollRun)
        .where(PayrollRun.id == row.id, PayrollRun.status.in_(("CALCULATED", "IN_REVIEW")))
        .values(status="APPROVED")
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"La liquidación {run_id} debe estar calculada para aprobarse (estado {row.status})")
    count = db.scalar(select(func.count(PayrollResult.id)).where(PayrollResult.payroll_run_id == row.id))
    review = db.scalar(select(PayrollTrace).where(
        PayrollTrace.payroll_run_id == row.id, PayrollTrace.event == "CALCULATION_REVIEW",
    ).order_by(PayrollTrace.id.desc()))
    incomplete = (review is None and row.run_type != "MONTHLY") or (review is not None and any(
        warning.get("type") in {"settlement_missing_rules", "settlement_incomplete"}
        for warning in review.detail.get("warnings", [])
    ))
    if not count or incomplete:
        db.rollback()
        raise HTTPException(status_code=409, detail=(
            "No se puede aprobar una liquidación vacía o incompleta. "
            "Revise las reglas de descuentos/contribuciones y las alertas del cálculo."
        ))
    db.add(PayrollApproval(payroll_run_id=row.id, user_id=user.id, status="APPROVED"))
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.post("/{run_id}/reopen", response_model=PayrollRunRead)
def reopen_payroll_run(
    run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    """Reopen a calculated run back to DRAFT (V2-25).

    Only CALCULATED/IN_REVIEW/ERROR runs reopen; the transition is recorded
    in the audit log. Approved runs need an annulment instead (PENDING).
    """
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    if row.status not in {"CALCULATED", "IN_REVIEW", "ERROR"}:
        raise HTTPException(status_code=409, detail="Solo se reabren liquidaciones calculadas o con error")
    before = row.status
    claimed = db.execute(
        update(PayrollRun)
        .where(PayrollRun.id == row.id, PayrollRun.status == before)
        .values(status="DRAFT", inputs_hash=None, results_hash=None, ruleset_id=None)
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El estado de la liquidación cambió")
    _clear_previous_results(db, row.id)
    db.add(AuditLog(
        organization_id=user.organization_id, user_id=user.id, action="payroll_run.reopened",
        entity_type="PayrollRun", entity_id=str(row.id),
        before={"status": before}, after={"status": "DRAFT"},
    ))
    commit_or_conflict(db)
    db.refresh(row)
    return row
