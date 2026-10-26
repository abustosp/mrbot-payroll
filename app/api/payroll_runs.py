# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import PayrollRunInput, PayrollRunRead
from app.auth.dependencies import require_role, require_user
from app.database.models import Company, PayrollApproval, PayrollRun, User
from app.database.session import get_db
from app.services.payroll_calculation import PayrollRunStateError, calculate_payroll_run

router = APIRouter(prefix="/payroll-runs", tags=["payroll-runs"])


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


@router.post("", response_model=PayrollRunRead, status_code=status.HTTP_201_CREATED)
def create_payroll_run(
    payload: PayrollRunInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    company = db.scalar(
        select(Company).where(
            Company.id == payload.company_id,
            Company.organization_id == user.organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
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
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    try:
        result = calculate_payroll_run(db, row)
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
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
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
    db.delete(row)
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{run_id}/approve", response_model=PayrollRunRead)
def approve_payroll_run(
    run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, PayrollRun, run_id, user.organization_id)
    if row.status not in {"CALCULATED", "IN_REVIEW"}:
        raise HTTPException(status_code=409, detail="La liquidación debe estar calculada para aprobarse")
    row.status = "APPROVED"
    db.add(PayrollApproval(payroll_run_id=row.id, user_id=user.id, status="APPROVED"))
    commit_or_conflict(db)
    db.refresh(row)
    return row
