# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import FormulaInput, FormulaRead, FormulaVersionInput
from app.auth.dependencies import require_role, require_user
from app.core.payroll_engine.types import FormulaDefinition as FormulaContract
from app.core.payroll_engine.validations import validate_formula as validate_formula_dsl
from app.database.models import AuditLog, FormulaDefinition, FormulaVersion, User
from app.database.session import get_db

router = APIRouter(prefix="/formulas", tags=["formulas"])


def latest_version(db: Session, formula: FormulaDefinition) -> FormulaVersion:
    version = db.scalar(
        select(FormulaVersion).where(
            FormulaVersion.formula_id == formula.id,
            FormulaVersion.version == formula.current_version,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Versión de fórmula no encontrada")
    return version


def formula_output(formula: FormulaDefinition, version: FormulaVersion) -> FormulaRead:
    return FormulaRead(
        id=formula.id,
        code=formula.code,
        description=formula.description,
        version=version.version,
        formula=version.expression,
        status=version.status,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
    )


@router.get("")
def list_formulas(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    statement = select(FormulaDefinition).where(
        FormulaDefinition.organization_id == user.organization_id
    ).order_by(FormulaDefinition.id)
    result = page(db, statement, limit, offset)
    result["items"] = [formula_output(row, latest_version(db, row)) for row in result["items"]]
    return result


@router.post("", response_model=FormulaRead, status_code=status.HTTP_201_CREATED)
def create_formula(
    payload: FormulaInput, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor")),
):
    row = FormulaDefinition(
        organization_id=user.organization_id,
        code=payload.code.strip(),
        description=payload.description,
        current_version=1,
    )
    db.add(row)
    db.flush()
    version = FormulaVersion(
        formula_id=row.id,
        version=1,
        expression=payload.formula,
        status="DRAFT",
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(version)
    commit_or_conflict(db)
    db.refresh(row)
    db.refresh(version)
    return formula_output(row, version)


def _periods_overlap(
    start_a: date,
    end_a: date | None,
    start_b: date,
    end_b: date | None,
) -> bool:
    """Inclusive overlap test; ``None`` means an open-ended period."""

    if end_a is not None and start_b > end_a:
        return False
    if end_b is not None and start_a > end_b:
        return False
    return True


def _validated_expression(
    formula: FormulaDefinition,
    payload: FormulaVersionInput,
) -> dict[str, Any]:
    """Validate the DSL tree and return a JSON-safe expression."""

    try:
        definition = FormulaContract.model_validate(
            {
                "code": formula.code,
                "description": formula.description,
                "formula": payload.formula,
                "valid_from": payload.valid_from,
                "valid_to": payload.valid_to,
            }
        )
        errors = validate_formula_dsl(definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"DSL inválido: {exc}") from exc
    if errors:
        raise HTTPException(status_code=422, detail={"message": "DSL inválido", "errors": errors})
    return definition.formula


@router.post(
    "/{formula_id}/versions",
    response_model=FormulaRead,
    status_code=status.HTTP_201_CREATED,
)
def create_formula_version(
    formula_id: int,
    payload: FormulaVersionInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Create the next formula version as a draft.

    The previous versions are never mutated: an approved version remains an
    immutable historical record. Overlapping validity periods are rejected
    instead of silently closing an approved version.
    """

    row = get_scoped(db, FormulaDefinition, formula_id, user.organization_id)
    expression = _validated_expression(row, payload)
    existing = db.scalars(
        select(FormulaVersion)
        .where(FormulaVersion.formula_id == row.id)
        .order_by(FormulaVersion.version)
    ).all()
    for version in existing:
        if _periods_overlap(
            payload.valid_from,
            payload.valid_to,
            version.valid_from,
            version.valid_to,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La vigencia se solapa con la versión "
                    f"{version.version} ({version.valid_from} - {version.valid_to or 'sin fin'})"
                ),
            )

    next_version = max((version.version for version in existing), default=0) + 1
    version = FormulaVersion(
        formula_id=row.id,
        version=next_version,
        expression=expression,
        status="DRAFT",
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(version)
    row.current_version = next_version
    db.flush()
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="formula.version_created",
            entity_type="FormulaVersion",
            entity_id=str(version.id),
            before=None,
            after={
                "formula_id": row.id,
                "formula_code": row.code,
                "version": version.version,
                "status": version.status,
                "formula": expression,
                "valid_from": version.valid_from.isoformat(),
                "valid_to": version.valid_to.isoformat() if version.valid_to else None,
            },
        )
    )
    commit_or_conflict(db)
    db.refresh(row)
    db.refresh(version)
    return formula_output(row, version)


@router.post("/{formula_id}/validate", response_model=FormulaRead)
def validate_formula(
    formula_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor")),
):
    row = get_scoped(db, FormulaDefinition, formula_id, user.organization_id)
    version = latest_version(db, row)
    if version.status not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=409, detail="Solo se validan fórmulas en borrador")
    try:
        definition = FormulaContract.model_validate(
            {
                "code": row.code,
                "description": row.description,
                "formula": version.expression,
                "valid_from": version.valid_from,
                "valid_to": version.valid_to,
            }
        )
        errors = validate_formula_dsl(definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"DSL inválido: {exc}") from exc
    if errors:
        raise HTTPException(status_code=422, detail={"message": "DSL inválido", "errors": errors})
    version.status = "VALIDATED"
    commit_or_conflict(db)
    return formula_output(row, version)


@router.post("/{formula_id}/approve", response_model=FormulaRead)
def approve_formula(
    formula_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin")),
):
    row = get_scoped(db, FormulaDefinition, formula_id, user.organization_id)
    version = latest_version(db, row)
    if version.status != "VALIDATED":
        raise HTTPException(status_code=409, detail="La fórmula debe estar validada antes de aprobarse")
    version.status = "APPROVED"
    version.approved_by = user.id
    version.approved_at = datetime.now(UTC)
    commit_or_conflict(db)
    return formula_output(row, version)
