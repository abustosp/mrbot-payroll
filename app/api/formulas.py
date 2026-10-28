# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped, page
from app.api.schemas import FormulaInput, FormulaRead, FormulaVersionInput
from app.auth.dependencies import require_role, require_user
from app.core.payroll_engine.calculator import EmployeeData, _base_variables
from app.core.payroll_engine.concepts import ConceptError, novelty_variables, to_decimal
from app.core.payroll_engine.types import FormulaContext
from app.core.payroll_engine.types import FormulaDefinition as FormulaContract
from app.core.payroll_engine.validations import validate_formula as validate_formula_dsl
from app.database.models import (
    AgreementCategory,
    AuditLog,
    CollectiveAgreement,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
    PayrollNovelty,
    User,
)
from app.database.session import get_db
from app.exporters.tabular import normalize_format, table_response

router = APIRouter(prefix="/formulas", tags=["formulas"])

FORMULA_EXPORT_COLUMNS = [
    "id", "code", "description", "version", "status", "valid_from", "valid_to",
]


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


def formula_output(
    formula: FormulaDefinition, version: FormulaVersion, warnings: list[str] | None = None,
) -> FormulaRead:
    return FormulaRead(
        id=formula.id,
        code=formula.code,
        description=formula.description,
        version=version.version,
        formula=version.expression,
        conditions=list(version.conditions or []),
        depends_on=list(version.depends_on or []),
        rounding=version.rounding,  # type: ignore[arg-type]
        status=version.status,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        warnings=list(warnings or []),
    )


def _known_variables() -> dict[str, Any]:
    """Sample the calculator's base variables so validation knows their types."""
    sample = _base_variables(
        EmployeeData(
            id="validacion",
            base_salary=Decimal("1000"),
            start_date=date(2020, 1, 1),
            agreement_category="X",
            workday_factor=Decimal("1"),
        ),
        date(2026, 6, 30),
    )
    known: dict[str, Any] = {}
    for name, value in sample.items():
        if isinstance(value, bool) or value is None:
            known[name] = value
            continue
        try:
            known[name] = to_decimal(value)
        except ConceptError:
            continue  # dates and free text are not usable inside the DSL
    return known


def _validation_context(
    db: Session,
    organization_id: int,
    *,
    candidate_code: str,
    valid_from: date,
    valid_to: date | None,
) -> tuple[FormulaContext, list[FormulaContract]]:
    """Build the B-08 validation context: known inputs + vigente definitions."""
    variables = _known_variables()
    parameters: dict[str, Any] = {}
    for row in db.scalars(select(NormativeParameter)).all():
        parameters.setdefault(row.code, Decimal("0"))
    # Parameters are also visible as plain variables in the calculator.
    for name, value in parameters.items():
        variables.setdefault(name, value)
        variables.setdefault(name.upper(), value)
        variables.setdefault(name.lower(), value)
    novelty_codes = set(
        db.scalars(
            select(PayrollNovelty.code).where(
                PayrollNovelty.organization_id == organization_id
            )
        ).all()
    )
    for code in novelty_codes:
        for name, value in novelty_variables(
            [{"code": code, "quantity": Decimal("0"), "amount": Decimal("0")}]
        ).items():
            variables.setdefault(name, value)
    concepts: dict[str, Any] = {}
    for code in db.scalars(
        select(FormulaDefinition.code).where(
            FormulaDefinition.organization_id == organization_id
        )
    ).all():
        concepts.setdefault(code, Decimal("0"))
    for code in db.scalars(
        select(PayrollConcept.code).where(
            PayrollConcept.organization_id == organization_id
        )
    ).all():
        concepts.setdefault(code, Decimal("0"))
    # The calculator exposes every computed concept as a concept_X variable.
    for code in list(concepts):
        for alias in {f"concept_{code}", f"concept_{code.upper()}", f"concept_{code.lower()}"}:
            variables.setdefault(alias, Decimal("0"))
    definitions: list[FormulaContract] = []
    for formula in db.scalars(
        select(FormulaDefinition).where(
            FormulaDefinition.organization_id == organization_id,
            FormulaDefinition.code != candidate_code,
        )
    ).all():
        latest = db.scalar(
            select(FormulaVersion)
            .where(FormulaVersion.formula_id == formula.id)
            .order_by(FormulaVersion.version.desc())
        )
        if latest is None:
            continue
        if latest.valid_from > (valid_to or latest.valid_from) or (
            latest.valid_to is not None and latest.valid_to < valid_from
        ):
            continue
        definitions.append(
            FormulaContract(code=formula.code, formula=latest.expression)
        )
    return (
        FormulaContext(
            variables=variables, parameters=parameters, concepts=concepts, functions={}
        ),
        definitions,
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


@router.get("/export")
def export_formulas(
    format: str = Query(default="csv", max_length=10),
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Descarga todas las fórmulas de la organización en csv, xlsx o json."""

    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = db.scalars(
        select(FormulaDefinition).where(
            FormulaDefinition.organization_id == user.organization_id
        ).order_by(FormulaDefinition.id)
    ).all()
    rows = [
        formula_output(row, latest_version(db, row)).model_dump(mode="json")
        for row in items
    ]
    return table_response(rows, FORMULA_EXPORT_COLUMNS, "formulas", fmt)


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
        conditions=list(payload.conditions),
        depends_on=list(payload.depends_on),
        rounding=(
            payload.rounding.model_dump(mode="json")
            if payload.rounding is not None
            else None
        ),
        status="DRAFT",
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(version)
    try:
        candidate: dict[str, Any] = {
            "code": row.code,
            "description": row.description,
            "formula": payload.formula,
            "conditions": list(payload.conditions),
            "depends_on": list(payload.depends_on),
            "valid_from": payload.valid_from,
            "valid_to": payload.valid_to,
        }
        if payload.rounding is not None:
            candidate["rounding"] = payload.rounding.model_dump(mode="json")
        definition = FormulaContract.model_validate(candidate)
        context, definitions = _validation_context(
            db,
            user.organization_id,
            candidate_code=row.code,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
        warnings = validate_formula_dsl(definition, context, definitions)
    except ValueError as exc:
        warnings = [f"DSL inválido: {exc}"]
    commit_or_conflict(db)
    db.refresh(row)
    db.refresh(version)
    return formula_output(row, version, warnings=warnings)


def _validated_fields(
    formula: FormulaDefinition,
    payload: FormulaVersionInput,
    db: Session,
    organization_id: int,
) -> dict[str, Any]:
    """Validate the DSL tree with context and return JSON-safe version fields."""

    try:
        candidate: dict[str, Any] = {
            "code": formula.code,
            "description": formula.description,
            "formula": payload.formula,
            "conditions": payload.conditions,
            "depends_on": payload.depends_on,
            "valid_from": payload.valid_from,
            "valid_to": payload.valid_to,
        }
        if payload.rounding is not None:
            candidate["rounding"] = payload.rounding.model_dump(mode="json")
        definition = FormulaContract.model_validate(candidate)
        context, definitions = _validation_context(
            db,
            organization_id,
            candidate_code=formula.code,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
        errors = validate_formula_dsl(definition, context, definitions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"DSL inválido: {exc}") from exc
    if errors:
        raise HTTPException(status_code=422, detail={"message": "DSL inválido", "errors": errors})
    return {
        "expression": definition.formula,
        "conditions": [dict(condition) for condition in definition.conditions],
        "depends_on": list(definition.depends_on),
        "rounding": definition.rounding.model_dump(mode="json"),
    }


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
    immutable historical record.  Validity ranges may overlap; when more than
    one approved version is applicable to a period, the highest version wins
    during payroll calculation.
    """

    row = get_scoped(db, FormulaDefinition, formula_id, user.organization_id)
    fields = _validated_fields(row, payload, db, user.organization_id)
    existing = db.scalars(
        select(FormulaVersion)
        .where(FormulaVersion.formula_id == row.id)
        .order_by(FormulaVersion.version)
    ).all()
    next_version = max((version.version for version in existing), default=0) + 1
    version = FormulaVersion(
        formula_id=row.id,
        version=next_version,
        expression=fields["expression"],
        conditions=fields["conditions"],
        depends_on=fields["depends_on"],
        rounding=fields["rounding"],
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
                "formula": fields["expression"],
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
        raise HTTPException(status_code=409, detail=f"Solo se validan fórmulas en borrador (fórmula {formula_id}, estado {version.status})")
    try:
        candidate = {
            "code": row.code,
            "description": row.description,
            "formula": version.expression,
            "conditions": version.conditions or [],
            "depends_on": version.depends_on or [],
            "valid_from": version.valid_from,
            "valid_to": version.valid_to,
        }
        if version.rounding:
            candidate["rounding"] = version.rounding
        definition = FormulaContract.model_validate(candidate)
        context, definitions = _validation_context(
            db,
            user.organization_id,
            candidate_code=row.code,
            valid_from=version.valid_from,
            valid_to=version.valid_to,
        )
        errors = validate_formula_dsl(definition, context, definitions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"DSL inválido: {exc}") from exc
    if errors:
        raise HTTPException(status_code=422, detail={"message": "DSL inválido", "errors": errors})
    version.status = "VALIDATED"
    commit_or_conflict(db)
    return formula_output(row, version)


class FormulaScopeInput(BaseModel):
    """Agreement scope for a formula (B-26; kept here, not in schemas.py).

    ``None`` clears the scope (the formula applies to every employee).
    """

    agreement_code: str | None = None
    category_code: str | None = None


@router.patch("/{formula_id}/scope", response_model=FormulaRead)
def set_formula_scope(
    formula_id: int,
    payload: FormulaScopeInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Scope a formula to one CCT/category so multi-CCT payrolls apply it
    only to matching employees (B-26). Unscoped formulas apply to everyone.
    Unknown agreement/category codes are rejected with 422."""

    row = get_scoped(db, FormulaDefinition, formula_id, user.organization_id)
    agreement = (payload.agreement_code or "").strip() or None
    category = (payload.category_code or "").strip() or None
    if agreement is not None and (
        db.scalar(
            select(CollectiveAgreement.id).where(CollectiveAgreement.code == agreement)
        )
        is None
    ):
        raise HTTPException(status_code=422, detail=f"Convenio {agreement!r} inexistente")
    if category is not None:
        statement = select(AgreementCategory.id).where(AgreementCategory.code == category)
        if agreement is not None:
            statement = statement.where(
                AgreementCategory.agreement_id.in_(
                    select(CollectiveAgreement.id).where(
                        CollectiveAgreement.code == agreement
                    )
                )
            )
        if db.scalar(statement) is None:
            raise HTTPException(status_code=422, detail=f"Categoría {category!r} inexistente")
    row.agreement_code = agreement
    row.category_code = category
    commit_or_conflict(db)
    db.refresh(row)
    return formula_output(row, latest_version(db, row))


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
