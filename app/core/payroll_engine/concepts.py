"""Helpers for payroll concepts and novelties.

This module deliberately contains no legal or collective-agreement formulas.  It only
normalises the data that feeds the DSL and turns a :class:`FormulaResult` into a
:class:`ConceptResult` that can be persisted or rendered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.payroll_engine.types import (
    ConceptNature,
    ConceptResult,
    FormulaDefinition,
    FormulaResult,
)

# Money and quantities are always handled as Decimal.  These aliases make the
# supported field names explicit and keep the normalisation in one place.
_CODE_FIELDS = ("code", "codigo", "código", "concept", "concepto", "tipo")
_QUANTITY_FIELDS = ("quantity", "cantidad", "qty")
_AMOUNT_FIELDS = ("amount", "importe", "value", "valor")
_UNIT_FIELDS = ("unit", "unidad")
_KIND_FIELDS = ("kind", "tipo_novedad", "tipo", "type", "clase")


class ConceptError(ValueError):
    """Raised when a concept, novelty or numeric value cannot be normalised."""


@dataclass(frozen=True, slots=True)
class NormalizedNovelty:
    """A novelty expressed with Decimal values and trimmed text fields."""

    code: str
    quantity: Decimal | None = None
    amount: Decimal | None = None
    unit: str | None = None
    kind: str | None = None

    @property
    def key(self) -> str:
        """Canonical key used to aggregate novelties of the same type."""

        return self.code.upper()

    @property
    def value(self) -> Decimal:
        """Monetary value exposed to formulas.

        Payroll novelties usually carry a total amount.  When only a quantity is
        supplied (for example overtime hours with a rate defined by a parameter),
        the quantity is exposed instead and the formula can multiply it by the rate.
        """

        if self.amount is not None:
            return self.amount
        if self.quantity is not None:
            return self.quantity
        return Decimal("0")


def _read_field(raw: Mapping[str, Any] | object, names: Iterable[str]) -> Any:
    for name in names:
        if isinstance(raw, Mapping):
            if name in raw:
                return raw[name]
        elif hasattr(raw, name):
            return getattr(raw, name)
    return None


def to_decimal(
    value: Any,
    *,
    field: str = "value",
    allow_none: bool = False,
) -> Decimal | None:
    """Convert a scalar to a finite Decimal.

    ``float`` inputs are converted through their string representation so no binary
    noise enters the calculation.  Callers should still prefer ``Decimal``, ``int``
    or numeric strings.  ``bool`` is rejected because it almost always indicates a
    programming error.
    """

    if value is None:
        if allow_none:
            return None
        raise ConceptError(f"{field} is required")

    if isinstance(value, bool):
        raise ConceptError(f"{field} must be numeric, not boolean")

    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, int):
            result = Decimal(value)
        elif isinstance(value, float):
            result = Decimal(str(value))
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                raise ConceptError(f"{field} is blank")
            result = Decimal(text)
        else:
            raise ConceptError(
                f"{field} must be int, str, float or Decimal, got {type(value).__name__}"
            )
    except InvalidOperation as exc:
        raise ConceptError(f"{field} is not a valid decimal: {value!r}") from exc

    if not result.is_finite():
        raise ConceptError(f"{field} must be a finite decimal")
    return result


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_novelty(raw: Mapping[str, Any] | object) -> NormalizedNovelty:
    """Normalise one novelty mapping or dataclass."""

    code = _optional_text(_read_field(raw, _CODE_FIELDS), field="novelty code")
    if code is None:
        raise ConceptError("novelty is missing required field 'code'")

    quantity = to_decimal(
        _read_field(raw, _QUANTITY_FIELDS),
        field=f"novelty {code!r} quantity",
        allow_none=True,
    )
    amount = to_decimal(
        _read_field(raw, _AMOUNT_FIELDS),
        field=f"novelty {code!r} amount",
        allow_none=True,
    )

    return NormalizedNovelty(
        code=code,
        quantity=quantity,
        amount=amount,
        unit=_optional_text(_read_field(raw, _UNIT_FIELDS), field="unit"),
        kind=_optional_text(_read_field(raw, _KIND_FIELDS), field="kind"),
    )


def normalize_novelties(
    novelties: Iterable[Mapping[str, Any] | object] | None,
) -> list[NormalizedNovelty]:
    """Normalise a sequence of novelties, preserving input order."""

    if not novelties:
        return []
    return [normalize_novelty(novelty) for novelty in novelties]


def aggregate_novelties(
    novelties: Iterable[Mapping[str, Any] | object] | None,
) -> dict[str, NormalizedNovelty]:
    """Aggregate novelties by code.

    The domain sums the values of novelties of the same type inside the payroll
    period.  Codes are compared case-insensitively; the first spelling is kept.
    """

    aggregated: dict[str, NormalizedNovelty] = {}
    for novelty in normalize_novelties(novelties):
        previous = aggregated.get(novelty.key)
        if previous is None:
            aggregated[novelty.key] = novelty
            continue

        quantity = _sum_optional(previous.quantity, novelty.quantity)
        amount = _sum_optional(previous.amount, novelty.amount)
        aggregated[novelty.key] = NormalizedNovelty(
            code=previous.code,
            quantity=quantity,
            amount=amount,
            unit=previous.unit or novelty.unit,
            kind=previous.kind or novelty.kind,
        )
    return aggregated


def _sum_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _add_aliases(target: dict[str, Any], name: str, value: Any) -> None:
    """Expose a variable under its exact, upper and lower spellings."""

    for variant in {name, name.upper(), name.lower()}:
        target.setdefault(variant, value)


def novelty_exposed_names(novelty: NormalizedNovelty) -> dict[str, Decimal]:
    """Map every variable spelling that reads one novelty to its scalar value.

    Single source for the spellings documented in :func:`novelty_variables`;
    the calculator reuses it to detect novelties consumed by no formula (B-11).
    """

    names: dict[str, Decimal] = {
        novelty.code: novelty.value,
        f"novedad_{novelty.code}": novelty.value,
    }
    if novelty.quantity is not None:
        for suffix in ("_cantidad", "_quantity"):
            names[f"{novelty.code}{suffix}"] = novelty.quantity
            names[f"novedad_{novelty.code}{suffix}"] = novelty.quantity
    if novelty.amount is not None:
        for suffix in ("_importe", "_amount"):
            names[f"{novelty.code}{suffix}"] = novelty.amount
            names[f"novedad_{novelty.code}{suffix}"] = novelty.amount
    return names


def novelty_variables(
    novelties: Iterable[Mapping[str, Any] | object] | None,
) -> dict[str, Decimal]:
    """Build the scalar variables a DSL formula can read from novelties.

    For a novelty ``HORAS_EXTRA`` the following variables are exposed (upper and
    lower case variants are also available):

    - ``HORAS_EXTRA`` / ``NOVEDAD_HORAS_EXTRA``: total amount, or quantity when no
      amount was supplied.
    - ``HORAS_EXTRA_CANTIDAD`` / ``HORAS_EXTRA_QUANTITY``: quantity.
    - ``HORAS_EXTRA_IMPORTE`` / ``HORAS_EXTRA_AMOUNT``: amount.
    """

    variables: dict[str, Decimal] = {}
    for novelty in aggregate_novelties(novelties).values():
        for name, value in novelty_exposed_names(novelty).items():
            _add_aliases(variables, name, value)
    return variables


def build_concept_result(
    definition: FormulaDefinition,
    result: FormulaResult,
    *,
    amount: Decimal | None = None,
    quantity: Decimal | None = None,
    unit_value: Decimal | None = None,
) -> ConceptResult:
    """Create the public result for a formula, keeping the audit trace."""

    trace = list(result.trace)
    if not result.conditions_met:
        trace.append("condition not met; amount forced to zero")
    final_amount = result.value if amount is None else amount
    trace.append(f"amount={final_amount}")

    return ConceptResult(
        code=definition.code,
        name=definition.description or definition.code,
        nature=definition.nature,
        amount=final_amount,
        quantity=quantity,
        unit_value=unit_value,
        trace=trace,
        source=definition.source,
    )


def concept_amounts_by_nature(
    items: Iterable[ConceptResult],
    nature: ConceptNature,
) -> Decimal:
    """Sum the amounts of items with a given nature (pure helper)."""

    return sum(
        (item.amount for item in items if item.nature == nature),
        start=Decimal("0"),
    )


__all__ = [
    "ConceptError",
    "NormalizedNovelty",
    "aggregate_novelties",
    "build_concept_result",
    "concept_amounts_by_nature",
    "normalize_novelty",
    "normalize_novelties",
    "novelty_exposed_names",
    "novelty_variables",
    "to_decimal",
]
