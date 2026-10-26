# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import ConceptInput, ConceptRead
from app.auth.dependencies import require_role, require_user
from app.database.models import PayrollConcept, User
from app.database.session import get_db

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("")
def list_concepts(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    statement = select(PayrollConcept).where(PayrollConcept.organization_id == user.organization_id).order_by(PayrollConcept.id)
    result = page(db, statement, limit, offset)
    result["items"] = [ConceptRead.model_validate(item) for item in result["items"]]
    return result


@router.post("", response_model=ConceptRead, status_code=status.HTTP_201_CREATED)
def create_concept(
    payload: ConceptInput, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor")),
):
    row = PayrollConcept(organization_id=user.organization_id, **payload.model_dump())
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.get("/{concept_id}", response_model=ConceptRead)
def get_concept(concept_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return get_scoped(db, PayrollConcept, concept_id, user.organization_id)


@router.put("/{concept_id}", response_model=ConceptRead)
def update_concept(
    concept_id: int, payload: ConceptInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, PayrollConcept, concept_id, user.organization_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.delete("/{concept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_concept(
    concept_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    db.delete(get_scoped(db, PayrollConcept, concept_id, user.organization_id))
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
