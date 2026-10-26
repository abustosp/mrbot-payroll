from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, Mapping

from pydantic import BaseModel, Field, field_validator


class RoundingMode(StrEnum):
    HALF_UP = "HALF_UP"
    HALF_EVEN = "HALF_EVEN"
    DOWN = "DOWN"
    UP = "UP"


class ConceptNature(StrEnum):
    REMUNERATIVE = "REMUNERATIVE"
    NON_REMUNERATIVE = "NON_REMUNERATIVE"
    DEDUCTION = "DEDUCTION"
    CONTRIBUTION = "CONTRIBUTION"
    AUXILIARY = "AUXILIARY"


class FormulaStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    OBSOLETE = "OBSOLETE"


class RoundingPolicy(BaseModel):
    decimals: int = Field(default=2, ge=0, le=6)
    mode: RoundingMode = RoundingMode.HALF_UP


class FormulaDefinition(BaseModel):
    """A declarative formula. The tree is interpreted, never executed as Python."""

    code: str
    description: str = ""
    formula: dict[str, Any]
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    rounding: RoundingPolicy = Field(default_factory=RoundingPolicy)
    depends_on: list[str] = Field(default_factory=list)
    nature: ConceptNature = ConceptNature.REMUNERATIVE
    valid_from: date | None = None
    valid_to: date | None = None
    source: str | None = None
    version: int = Field(default=1, ge=1)
    status: FormulaStatus = FormulaStatus.DRAFT
    tests: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("formula code cannot be blank")
        return value


@dataclass(slots=True)
class FormulaContext:
    """All values available to a formula, already resolved for the period."""

    variables: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    concepts: Mapping[str, Any] = field(default_factory=dict)
    functions: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    period: date | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FormulaResult:
    value: Decimal
    trace: list[str] = field(default_factory=list)
    dependencies: set[str] = field(default_factory=set)
    conditions_met: bool = True


@dataclass(slots=True)
class ConceptResult:
    code: str
    name: str
    nature: ConceptNature
    amount: Decimal
    quantity: Decimal | None = None
    unit_value: Decimal | None = None
    trace: list[str] = field(default_factory=list)
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "nature": self.nature.value,
            "amount": str(self.amount),
            "quantity": None if self.quantity is None else str(self.quantity),
            "unit_value": None if self.unit_value is None else str(self.unit_value),
            "trace": list(self.trace),
            "source": self.source,
        }


@dataclass(slots=True)
class PayrollResult:
    employee_id: str
    period: date
    items: list[ConceptResult] = field(default_factory=list)
    remunerative: Decimal = Decimal("0")
    non_remunerative: Decimal = Decimal("0")
    deductions: Decimal = Decimal("0")
    contributions: Decimal = Decimal("0")
    gross: Decimal = Decimal("0")
    net: Decimal = Decimal("0")
    employer_cost: Decimal = Decimal("0")
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "period": self.period.isoformat(),
            "items": [item.to_dict() for item in self.items],
            "remunerative": str(self.remunerative),
            "non_remunerative": str(self.non_remunerative),
            "deductions": str(self.deductions),
            "contributions": str(self.contributions),
            "gross": str(self.gross),
            "net": str(self.net),
            "employer_cost": str(self.employer_cost),
            "trace": list(self.trace),
        }

