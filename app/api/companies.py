# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import CompanyInput, CompanyRead
from app.auth.dependencies import require_role, require_user
from app.database.models import Company, User
from app.database.session import get_db
from app.exporters.tabular import normalize_format, table_response

router = APIRouter(prefix="/companies", tags=["companies"])

COMPANY_EXPORT_COLUMNS = [
    "id", "cuit", "legal_name", "trade_name", "tax_activity", "address", "active",
]


@router.get("")
def list_companies(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    statement = select(Company).where(Company.organization_id == user.organization_id).order_by(Company.id)
    result = page(db, statement, limit, offset)
    result["items"] = [CompanyRead.model_validate(item) for item in result["items"]]
    return result


@router.get("/export")
def export_companies(
    format: str = Query(default="csv", max_length=10),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Descarga todas las empresas de la organización en csv, xlsx o json."""

    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = db.scalars(
        select(Company).where(
            Company.organization_id == user.organization_id
        ).order_by(Company.id)
    ).all()
    rows = [CompanyRead.model_validate(item).model_dump(mode="json") for item in items]
    return table_response(rows, COMPANY_EXPORT_COLUMNS, "empresas", fmt)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CompanyInput, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor")),
):
    row = Company(organization_id=user.organization_id, **payload.model_dump())
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return get_scoped(db, Company, company_id, user.organization_id)


@router.put("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: int, payload: CompanyInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, Company, company_id, user.organization_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(
    company_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, Company, company_id, user.organization_id)
    db.delete(row)
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
