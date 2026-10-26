"""Configurable contribution and progressive income-tax calculations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.normative.parameters import ParameterVersion, validate_no_overlaps
from app.jurisdictions.argentina.validation import parse_period

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_contributions(
    remunerative_base: Decimal,
    period: date | str,
    parameters: Iterable[ParameterVersion],
) -> dict[str, dict[str, Decimal]]:
    """Calculate demo/configured worker and employer amounts from versioned rates."""
    base = Decimal(str(remunerative_base))
    if not base.is_finite() or base < 0:
        raise ValueError("La base remunerativa debe ser un Decimal finito no negativo.")
    effective_date = parse_period(period)
    versions = tuple(parameters)
    validate_no_overlaps(versions)
    groups = {
        "employee": (
            "employee.retirement_rate",
            "employee.pami_rate",
            "employee.health_rate",
        ),
        "employer": (
            "employer.retirement_rate",
            "employer.pami_rate",
            "employer.health_rate",
            "employer.family_allowance_rate",
            "employer.employment_fund_rate",
            "employer.work_risk_rate",
        ),
    }
    result: dict[str, dict[str, Decimal]] = {name: {} for name in groups}
    for group, codes in groups.items():
        for code in codes:
            match = next(
                (
                    item
                    for item in versions
                    if item.code == code
                    and item.valid_from <= effective_date
                    and (item.valid_to is None or effective_date <= item.valid_to)
                ),
                None,
            )
            if match is None:
                raise LookupError(f"Falta el parámetro vigente {code} para {effective_date:%Y%m}.")
            if not Decimal(0) <= match.value <= Decimal(1):
                raise ValueError(f"La alícuota {code} debe ser una fracción entre 0 y 1.")
            result[group][code] = money(base * match.value)
    return result


@dataclass(frozen=True, slots=True)
class IncomeTaxBracketVersion:
    """One versioned progressive tax interval; rates and amounts are data."""

    code: str
    lower_limit: Decimal
    upper_limit: Decimal | None
    fixed_amount: Decimal
    rate: Decimal
    valid_from: date
    valid_to: date | None = None
    published_at: date | None = None
    source: str = ""
    version: int = 1
    status: str = "draft"

    def __post_init__(self) -> None:
        for field_name in ("lower_limit", "fixed_amount", "rate"):
            value = Decimal(str(getattr(self, field_name)))
            if not value.is_finite():
                raise ValueError(f"{field_name} debe ser finito")
            object.__setattr__(self, field_name, value)
        if self.upper_limit is not None:
            upper = Decimal(str(self.upper_limit))
            if not upper.is_finite() or upper <= self.lower_limit:
                raise ValueError("upper_limit debe ser mayor que lower_limit")
            object.__setattr__(self, "upper_limit", upper)
        if self.lower_limit < 0 or self.fixed_amount < 0 or not 0 <= self.rate <= 1:
            raise ValueError("Tramo de Ganancias inválido")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from")


def select_income_tax_brackets(
    brackets: Iterable[IncomeTaxBracketVersion], period: date | str
) -> tuple[IncomeTaxBracketVersion, ...]:
    effective_date = parse_period(period)
    active = tuple(
        item
        for item in brackets
        if item.valid_from <= effective_date
        and (item.valid_to is None or effective_date <= item.valid_to)
    )
    active = tuple(sorted(active, key=lambda item: item.lower_limit))
    if not active:
        raise LookupError(f"Falta la tabla de Ganancias vigente para {effective_date:%Y%m}.")
    if len({item.code for item in active}) != len(active):
        raise ValueError("Hay versiones de tramos de Ganancias superpuestas.")
    for index, bracket in enumerate(active):
        if index and bracket.lower_limit != active[index - 1].upper_limit:
            raise ValueError("Los tramos de Ganancias deben ser contiguos y no superponerse.")
        if index < len(active) - 1 and bracket.upper_limit is None:
            raise ValueError("Solo el último tramo puede ser abierto.")
    if active[-1].upper_limit is not None:
        raise ValueError("El último tramo de Ganancias debe ser abierto.")
    return active


def calculate_income_tax(
    taxable_base: Decimal,
    period: date | str,
    brackets: Iterable[IncomeTaxBracketVersion],
) -> Decimal:
    """Apply the active marginal bracket table to a nonnegative tax base."""
    base = Decimal(str(taxable_base))
    if not base.is_finite() or base < 0:
        raise ValueError("La base imponible debe ser un Decimal finito no negativo.")
    for bracket in select_income_tax_brackets(brackets, period):
        if bracket.upper_limit is None or base < bracket.upper_limit:
            return money(bracket.fixed_amount + (base - bracket.lower_limit) * bracket.rate)
    raise AssertionError("unbounded final bracket was validated")
