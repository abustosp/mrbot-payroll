from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.guards import ContractInUseError, ScaleInUseError


def page(db: Session, statement, limit: int, offset: int) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.limit(limit).offset(offset)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_scoped(db: Session, model: Any, resource_id: int, organization_id: int):
    row = db.scalar(select(model).where(model.id == resource_id, model.organization_id == organization_id))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Recurso {resource_id} no encontrado")
    return row


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicto con una clave única o referencia existente") from exc
    except (ScaleInUseError, ContractInUseError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
