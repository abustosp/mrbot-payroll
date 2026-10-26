"""Pydantic contracts for the supervised agreement-analysis pipeline.

These schemas are the boundary between an untrusted LLM response and the rest of
the payroll system. They deliberately contain no executable expressions: a
formula is always a JSON tree using the declarative DSL from ``plan.md`` 6.2.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.payroll_engine.types import (
    ConceptNature,
    FormulaDefinition,
    FormulaStatus,
    RoundingPolicy,
)

CONTENT_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
CODE_PATTERN = r"^[A-Za-z][A-Za-z0-9_.:-]*$"


def _reject_unsafe_decimal(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("boolean values are not valid decimals")
    # JSON numbers arrive as int/float; Pydantic converts them through their
    # decimal string representation, and every stored value is a Decimal.
    return value


def _ensure_finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("decimal value must be finite (no NaN or Infinity)")
    return value


FiniteDecimal = Annotated[
    Decimal,
    BeforeValidator(_reject_unsafe_decimal),
    AfterValidator(_ensure_finite),
]


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _finite_decimal_or_none(value: Any) -> Any:
    """Best-effort conversion used by ``LLMUsage`` for provider-reported cost."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class AISchema(BaseModel):
    """Base schema: immutable, strict about unknown fields, trims strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"


class ParameterUnit(StrEnum):
    CURRENCY = "currency"
    PERCENTAGE = "percentage"  # stored as a decimal fraction: 0.01 == 1 %
    QUANTITY = "quantity"
    DAYS = "days"
    MONTHS = "months"
    RATIO = "ratio"
    INDEX = "index"
    OTHER = "other"


class SourceReference(AISchema):
    """Traceability anchor for every proposed item.

    ``content_hash`` is filled by :func:`app.ai.analysis.analyze_agreement` from
    the actual document. Models should not invent it.
    """

    document_id: str = Field(min_length=1, max_length=200)
    version: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("version", "document_version"),
    )
    page: int | None = Field(default=None, ge=1)
    article: str | None = Field(default=None, max_length=300)
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)

    @field_validator("article", "content_hash", mode="before")
    @classmethod
    def _empty_optional_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("document_id", "version")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source fields cannot be blank")
        return value


class DocumentMetadata(AISchema):
    """Identity of the document being analyzed."""

    document_id: str = Field(min_length=1, max_length=200)
    version: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("version", "document_version"),
    )
    title: str | None = Field(default=None, max_length=500)
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    source_path: str | None = Field(default=None, max_length=2000)
    jurisdiction: str | None = Field(default=None, max_length=200)

    @field_validator("title", "content_hash", "source_path", "jurisdiction", mode="before")
    @classmethod
    def _empty_optional_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("document_id", "version")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document identity fields cannot be blank")
        return value


class LLMUsage(AISchema):
    """Optional provider accounting. Recorded only when the provider reports it."""

    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: FiniteDecimal | None = None

    @field_validator("cost_usd", mode="before")
    @classmethod
    def _coerce_cost(cls, value: Any) -> Any:
        return _finite_decimal_or_none(value)


class ValidationIssue(AISchema):
    """A single finding produced by deterministic validation."""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    path: str = Field(default="", max_length=1000)


class ValidationReport(AISchema):
    """Outcome of structural validation. It never represents an approval."""

    is_valid: bool
    formula_code: str | None = Field(default=None, max_length=200)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    engine_validator: str | None = Field(default=None, max_length=300)
    validated_at: datetime
    validator_version: str = "1.0"


class SuggestedTest(AISchema):
    """A human-reviewable numeric case for the proposed formula."""

    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    inputs: dict[str, FiniteDecimal] = Field(default_factory=dict)
    expected: FiniteDecimal
    period: date | None = None
    tolerance: FiniteDecimal = Decimal("0")

    @field_validator("tolerance")
    @classmethod
    def _non_negative_tolerance(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("tolerance cannot be negative")
        return value


def _validate_effective_range(model: Any) -> Any:
    valid_from = getattr(model, "effective_from", None)
    valid_to = getattr(model, "effective_to", None)
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError("effective_to cannot be earlier than effective_from")
    return model


class ProposedConcept(AISchema):
    code: str = Field(min_length=1, max_length=100, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    nature: ConceptNature = ConceptNature.REMUNERATIVE
    source: SourceReference
    effective_from: date | None = None
    effective_to: date | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _range(self) -> Self:
        return _validate_effective_range(self)


class ProposedParameter(AISchema):
    code: str = Field(min_length=1, max_length=100, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    value: FiniteDecimal
    unit: ParameterUnit = ParameterUnit.OTHER
    source: SourceReference
    effective_from: date | None = None
    effective_to: date | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _range(self) -> Self:
        return _validate_effective_range(self)


class ProposedFormula(AISchema):
    """A formula proposal.

    ``formula`` is a declarative DSL tree, never Python source. ``status`` is
    managed exclusively by :mod:`app.ai.proposals`; parsing a model response
    always forces ``draft``.
    """

    code: str = Field(min_length=1, max_length=100, pattern=CODE_PATTERN)
    description: str = Field(default="", max_length=2000)
    formula: dict[str, Any]
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    rounding: RoundingPolicy = Field(default_factory=RoundingPolicy)
    variables: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    nature: ConceptNature = ConceptNature.REMUNERATIVE
    source: SourceReference
    effective_from: date
    effective_to: date | None = None
    tests: list[SuggestedTest] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.DRAFT
    approved_by: str | None = Field(default=None, max_length=200)
    approved_at: datetime | None = None
    rejected_by: str | None = Field(default=None, max_length=200)
    rejected_at: datetime | None = None
    rejection_reason: str | None = Field(default=None, max_length=2000)
    validation: ValidationReport | None = None

    @field_validator("variables", "depends_on")
    @classmethod
    def _clean_references(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("formula references cannot be blank")
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    @field_validator("approved_by", "rejected_by", "rejection_reason", mode="before")
    @classmethod
    def _empty_optional_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _range(self) -> Self:
        _validate_effective_range(self)
        if self.status is ProposalStatus.APPROVED and not self.approved_by:
            raise ValueError("approved proposals require approved_by")
        return self

    def to_formula_definition(self) -> FormulaDefinition:
        """Convert to the engine contract, always as a ``DRAFT`` rule.

        This method is intentionally incapable of producing an approved rule:
        approval in the AI package is a review record, not a publication step.
        """

        source = f"{self.source.document_id}@{self.source.version}"
        if self.source.page is not None:
            source += f", page {self.source.page}"
        if self.source.article:
            source += f", {self.source.article}"
        return FormulaDefinition(
            code=self.code,
            description=self.description,
            formula=dict(self.formula),
            conditions=[dict(condition) for condition in self.conditions],
            rounding=self.rounding,
            depends_on=list(self.depends_on),
            nature=self.nature,
            valid_from=self.effective_from,
            valid_to=self.effective_to,
            source=source,
            status=FormulaStatus.DRAFT,
            tests=[test.model_dump(mode="json") for test in self.tests],
        )


class AgreementAnalysis(AISchema):
    """Structured interpretation of one agreement document.

    It is a proposal only. Nothing in this object is published to the payroll
    engine, and every formula starts in ``draft``.
    """

    analysis_version: str = "1.0"
    document: DocumentMetadata
    summary: str = Field(min_length=1, max_length=8000)
    agreement_number: str | None = Field(default=None, max_length=200)
    agreement_title: str | None = Field(default=None, max_length=500)
    jurisdiction: str | None = Field(default=None, max_length=200)
    effective_from: date | None = None
    effective_to: date | None = None
    concepts: list[ProposedConcept] = Field(default_factory=list)
    parameters: list[ProposedParameter] = Field(default_factory=list)
    formulas: list[ProposedFormula] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    security_warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    untrusted_content: bool = True
    provider_usage: LLMUsage | None = None
    analyzed_at: datetime

    @field_validator(
        "agreement_number", "agreement_title", "jurisdiction", mode="before"
    )
    @classmethod
    def _empty_optional_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _date_range(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot be earlier than effective_from")
        return self

    @model_validator(mode="after")
    def _unique_codes(self) -> Self:
        for label, items in (
            ("concept", self.concepts),
            ("parameter", self.parameters),
            ("formula", self.formulas),
        ):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for item in items:
                if item.code in seen:
                    duplicates.add(item.code)
                seen.add(item.code)
            if duplicates:
                raise ValueError(
                    f"duplicate {label} code(s) in analysis: "
                    f"{', '.join(sorted(duplicates))}"
                )
        return self

    def formula(self, code: str) -> ProposedFormula | None:
        """Return a formula proposal by code, if present."""

        for formula in self.formulas:
            if formula.code == code:
                return formula
        return None
