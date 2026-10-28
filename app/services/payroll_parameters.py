"""Resolve effective parameters without mixing agreements or categories."""

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.models import NormativeParameter


def load_parameters(db: Session, period: date) -> list[NormativeParameter]:
    return list(db.scalars(select(NormativeParameter).where(
        NormativeParameter.jurisdiction == "AR",
        NormativeParameter.valid_from <= period,
        or_(NormativeParameter.valid_to.is_(None), NormativeParameter.valid_to >= period),
    ).order_by(NormativeParameter.id)).all())


def resolve_parameters(
    rows: list[NormativeParameter], agreement_code: str = "", category_code: str = "",
) -> dict[str, Decimal]:
    selected: dict[str, NormativeParameter] = {}
    for row in rows:
        if row.agreement_code and row.agreement_code != agreement_code:
            continue
        if row.category_code and row.category_code != category_code:
            continue
        previous = selected.get(row.code)
        priority = (bool(row.agreement_code), bool(row.category_code))
        if previous is None or priority > (bool(previous.agreement_code), bool(previous.category_code)):
            selected[row.code] = row
        elif priority == (bool(previous.agreement_code), bool(previous.category_code)):
            raise ValueError(
                f"Parámetro {row.code}: vigencias superpuestas en el mismo alcance "
                f"({row.agreement_code or 'global'}/{row.category_code or 'todas'})."
            )
    return {code: row.value for code, row in selected.items()}


def parameter_snapshot(rows: list[NormativeParameter]) -> list[dict[str, object]]:
    return [{
        "id": row.id, "code": row.code, "value": str(row.value),
        "agreement_code": row.agreement_code, "category_code": row.category_code,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "version": row.version,
    } for row in rows]
