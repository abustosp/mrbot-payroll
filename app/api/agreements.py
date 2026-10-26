# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, page
from app.api.schemas import AgreementInput, AgreementRead
from app.auth.dependencies import require_role, require_user
from app.database.models import CollectiveAgreement, User
from app.database.session import get_db

router = APIRouter(prefix="/agreements", tags=["agreements"])


def get_agreement(db: Session, agreement_id: int):
    row = db.get(CollectiveAgreement, agreement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Convenio no encontrado")
    return row


@router.get("")
def list_agreements(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), _: User = Depends(require_user),
):
    result = page(db, select(CollectiveAgreement).order_by(CollectiveAgreement.id), limit, offset)
    result["items"] = [AgreementRead.model_validate(item) for item in result["items"]]
    return result


@router.post("", response_model=AgreementRead, status_code=status.HTTP_201_CREATED)
def create_agreement(
    payload: AgreementInput, db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    row = CollectiveAgreement(**payload.model_dump())
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.get("/{agreement_id}", response_model=AgreementRead)
def read_agreement(agreement_id: int, db: Session = Depends(get_db), _: User = Depends(require_user)):
    return get_agreement(db, agreement_id)


@router.put("/{agreement_id}", response_model=AgreementRead)
def update_agreement(
    agreement_id: int, payload: AgreementInput, db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    row = get_agreement(db, agreement_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.delete("/{agreement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agreement(
    agreement_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("admin")),
):
    db.delete(get_agreement(db, agreement_id))
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
