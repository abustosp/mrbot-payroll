# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import EmployeeInput, EmployeeRead
from app.auth.dependencies import require_role, require_user
from app.database.models import Employee, User
from app.database.session import get_db
from app.exporters.tabular import normalize_format, table_response

router = APIRouter(prefix="/employees", tags=["employees"])

EMPLOYEE_EXPORT_COLUMNS = [
    "id", "employee_code", "first_name", "last_name", "cuil", "email",
    "birth_date", "hire_date", "termination_date", "address", "active",
]


@router.get("")
def list_employees(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    statement = select(Employee).where(Employee.organization_id == user.organization_id).order_by(Employee.id)
    result = page(db, statement, limit, offset)
    result["items"] = [EmployeeRead.model_validate(item) for item in result["items"]]
    return result


@router.get("/export")
def export_employees(
    format: str = Query(default="csv", max_length=10),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Descarga todos los empleados de la organización en csv, xlsx o json."""

    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = db.scalars(
        select(Employee).where(
            Employee.organization_id == user.organization_id
        ).order_by(Employee.id)
    ).all()
    rows = [EmployeeRead.model_validate(item).model_dump(mode="json") for item in items]
    return table_response(rows, EMPLOYEE_EXPORT_COLUMNS, "empleados", fmt)


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeInput, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor")),
):
    row = Employee(organization_id=user.organization_id, **payload.model_dump())
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.get("/{employee_id}", response_model=EmployeeRead)
def get_employee(employee_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return get_scoped(db, Employee, employee_id, user.organization_id)


@router.put("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: int, payload: EmployeeInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, Employee, employee_id, user.organization_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    employee_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, Employee, employee_id, user.organization_id)
    db.delete(row)
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
