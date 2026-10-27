"""Reportes internos de control en formatos descargables.

Equivalencia libro de sueldos (V2-29, parte segura): el libro se cubre con
la planilla interna F.931 (``GET /reports/f931/{run_id}.xlsx``) más los
recibos por empleado; el agregado por concepto está en
``GET /reports/payroll-summary/{run_id}``. El layout legal completo del
libro rubricado sigue PENDING (propuesta en el reporte del sprint).
"""

# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_user
from app.database.models import (
    Company,
    Employee,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.exporters.excel.f931 import (
    REPORTABLE_STATUSES,
    XLSX_MEDIA_TYPE,
    build_f931_workbook,
    f931_filename,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/f931/{run_id}.xlsx", response_class=Response)
def export_f931_workbook(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    """Download the internal F.931 control workbook for one calculated run."""

    run = db.scalar(
        select(PayrollRun).where(
            PayrollRun.id == run_id,
            PayrollRun.organization_id == user.organization_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada")
    if run.status not in REPORTABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "La liquidación debe estar calculada, aprobada o cerrada para generar "
                "la planilla interna F.931"
            ),
        )

    company = db.scalar(
        select(Company).where(
            Company.id == run.company_id,
            Company.organization_id == user.organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa de la liquidación no encontrada")

    results = db.scalars(
        select(PayrollResult)
        .where(PayrollResult.payroll_run_id == run.id)
        .order_by(PayrollResult.employee_id)
    ).all()
    items = db.scalars(
        select(PayrollItem)
        .join(PayrollResult, PayrollResult.id == PayrollItem.payroll_result_id)
        .where(PayrollResult.payroll_run_id == run.id)
        .order_by(PayrollResult.employee_id, PayrollItem.id)
    ).all()
    employee_ids = [result.employee_id for result in results]
    employees = (
        db.scalars(
            select(Employee)
            .where(
                Employee.id.in_(employee_ids),
                Employee.organization_id == user.organization_id,
            )
            .order_by(Employee.id)
        ).all()
        if employee_ids
        else []
    )

    content = build_f931_workbook(run, results, items, employees, company)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{f931_filename(run)}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/payroll-summary/{run_id}")
def payroll_summary(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    """Agregado por concepto de una corrida calculada (V2-29)."""
    run = db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == user.organization_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada")
    if run.status not in REPORTABLE_STATUSES:
        raise HTTPException(status_code=409, detail="La liquidación debe estar calculada para resumirse")
    rows = db.execute(select(PayrollItem.code, PayrollItem.nature, func.count(PayrollItem.id), func.sum(PayrollItem.amount)).join(PayrollResult, PayrollResult.id == PayrollItem.payroll_result_id).where(PayrollResult.payroll_run_id == run.id).group_by(PayrollItem.code, PayrollItem.nature).order_by(PayrollItem.code)).all()
    by_concept = [{"code": code, "nature": nature, "employees": count, "total": str(total)} for code, nature, count, total in rows]
    employees_total = db.scalar(select(func.count(func.distinct(PayrollResult.employee_id))).where(PayrollResult.payroll_run_id == run.id)) or 0
    return {"payroll_run_id": run.id, "status": run.status, "employees_total": employees_total, "by_concept": by_concept}


__all__ = ["router"]
