"""Configurable taxable bases.

The module only answers one question: *how much of the already calculated payroll is
taxable for a given base?*  It intentionally knows nothing about legal rates or
percentages.  Minimums and caps are parameter names resolved by the caller, so the
same code works for any jurisdiction and for any validity period.

Typical wiring::

    rule = TaxBaseRule(
        code="REMUNERATIVE",
        natures=frozenset({ConceptNature.REMUNERATIVE}),
        minimum_parameter="base_minima_remunerativa",
        maximum_parameter="base_maxima_remunerativa",
    )
    base = compute_tax_base(rule, result.items, parameters)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.payroll_engine.concepts import ConceptError, to_decimal
from app.core.payroll_engine.rounding import quantize as quantize_value
from app.core.payroll_engine.types import (
    ConceptNature,
    ConceptResult,
    RoundingPolicy,
)


class TaxBaseError(ValueError):
    """Raised when a taxable-base rule or parameter is invalid."""


@dataclass(frozen=True, slots=True)
class TaxBaseRule:
    """Declarative definition of a taxable base.

    ``natures`` selects which concept natures enter the base.  ``include_codes`` can
    further restrict the base to an explicit set of concept codes; ``exclude_codes``
    always removes codes, even when their nature matches.  ``minimum_parameter`` and
    ``maximum_parameter`` are keys looked up in the payroll parameter mapping.  A
    missing or ``None`` parameter means "no limit".
    """

    code: str
    natures: frozenset[ConceptNature] = frozenset({ConceptNature.REMUNERATIVE})
    include_codes: frozenset[str] | None = None
    exclude_codes: frozenset[str] = frozenset()
    minimum_parameter: str | None = None
    maximum_parameter: str | None = None
    rounding: RoundingPolicy | None = None

    def __post_init__(self) -> None:
        code = str(self.code).strip()
        if not code:
            raise TaxBaseError("tax base code cannot be blank")
        object.__setattr__(self, "code", code)

        natures = self.natures
        if isinstance(natures, ConceptNature):
            natures = frozenset({natures})
        else:
            natures = frozenset(natures)
        if not natures:
            raise TaxBaseError(f"tax base {code!r} must select at least one concept nature")
        object.__setattr__(self, "natures", natures)

        if self.include_codes is not None:
            object.__setattr__(
                self,
                "include_codes",
                frozenset(_normalise_code(value) for value in self.include_codes),
            )
        object.__setattr__(
            self,
            "exclude_codes",
            frozenset(_normalise_code(value) for value in self.exclude_codes),
        )

        for field_name in ("minimum_parameter", "maximum_parameter"):
            value = getattr(self, field_name)
            if value is not None:
                text = str(value).strip()
                if not text:
                    raise TaxBaseError(
                        f"tax base {code!r} has a blank {field_name}"
                    )
                object.__setattr__(self, field_name, text)


def _normalise_code(value: Any) -> str:
    return str(value).strip().upper()


def _item_code(item: ConceptResult | Mapping[str, Any]) -> str:
    if isinstance(item, Mapping):
        code = item.get("code")
    else:
        code = item.code
    return _normalise_code(code)


def _item_nature(item: ConceptResult | Mapping[str, Any]) -> ConceptNature:
    if isinstance(item, Mapping):
        nature = item.get("nature")
    else:
        nature = item.nature
    if isinstance(nature, ConceptNature):
        return nature
    try:
        return ConceptNature(str(nature))
    except ValueError as exc:
        raise TaxBaseError(f"unknown concept nature {nature!r}") from exc


def _item_amount(item: ConceptResult | Mapping[str, Any]) -> Decimal:
    if isinstance(item, Mapping):
        amount = item.get("amount")
    else:
        amount = item.amount
    try:
        value = to_decimal(amount, field="concept amount")
    except ConceptError as exc:
        raise TaxBaseError(str(exc)) from exc
    if value is None:  # pragma: no cover - to_decimal only returns None with allow_none
        raise TaxBaseError("concept amount is required")
    return value


def item_matches_rule(
    rule: TaxBaseRule,
    item: ConceptResult | Mapping[str, Any],
) -> bool:
    """Return whether an item belongs to the taxable base described by ``rule``."""

    code = _item_code(item)
    if code in rule.exclude_codes:
        return False
    if rule.include_codes is not None and code not in rule.include_codes:
        return False
    return _item_nature(item) in rule.natures


def filter_taxable_items(
    rule: TaxBaseRule,
    items: Iterable[ConceptResult | Mapping[str, Any]],
) -> list[ConceptResult | Mapping[str, Any]]:
    """Return the items selected by ``rule`` in their original order."""

    return [item for item in items if item_matches_rule(rule, item)]


def _parameter_value(
    parameters: Mapping[str, Any],
    name: str | None,
    *,
    rule: TaxBaseRule,
    kind: str,
) -> Decimal | None:
    if name is None:
        return None
    if name not in parameters:
        return None
    raw = parameters[name]
    if raw is None:
        return None
    try:
        value = to_decimal(raw, field=f"{kind} parameter {name!r}")
    except ConceptError as exc:
        raise TaxBaseError(f"tax base {rule.code!r}: {exc}") from exc
    if value is None:  # pragma: no cover - defensive
        return None
    if value < 0:
        raise TaxBaseError(
            f"tax base {rule.code!r}: {kind} parameter {name!r} cannot be negative"
        )
    return value


def apply_limits(
    amount: Decimal,
    rule: TaxBaseRule,
    parameters: Mapping[str, Any],
) -> Decimal:
    """Apply the configured minimum and cap, returning the limited amount."""

    base = to_decimal(amount, field=f"tax base {rule.code!r} amount")
    if base is None:  # pragma: no cover - defensive
        raise TaxBaseError(f"tax base {rule.code!r} amount is required")

    minimum = _parameter_value(
        parameters,
        rule.minimum_parameter,
        rule=rule,
        kind="minimum",
    )
    maximum = _parameter_value(
        parameters,
        rule.maximum_parameter,
        rule=rule,
        kind="maximum",
    )
    if minimum is not None and maximum is not None and minimum > maximum:
        raise TaxBaseError(
            f"tax base {rule.code!r}: minimum {minimum} is greater than maximum {maximum}"
        )

    if minimum is not None and base < minimum:
        base = minimum
    if maximum is not None and base > maximum:
        base = maximum
    return base


def quantize_base(amount: Decimal, policy: RoundingPolicy) -> Decimal:
    """Quantize a base with the policy attached to the rule."""

    return quantize_value(amount, policy)


def require_tax_base_limits(
    parameters: Mapping[str, Any],
    *,
    code: str = "REMUNERATIVE",
    minimum_parameter: str = "base_minima_remunerativa",
    maximum_parameter: str = "base_maxima_remunerativa",
) -> TaxBaseRule:
    """Build the standard base rule, failing explicitly without approved limits.

    Mechanism for B-03: legal caps/floors are pending sign-off (D-1), so no
    value is invented here. Callers get a rule wired to the approved
    parameters, or a ``TaxBaseError`` naming the missing ones.
    """

    missing = [
        name
        for name in (minimum_parameter, maximum_parameter)
        if parameters.get(name) is None
    ]
    if missing:
        raise TaxBaseError(
            f"tax base {code!r}: faltan los parámetros aprobados "
            + ", ".join(repr(name) for name in missing)
            + " (valores pendientes D-1)"
        )
    return TaxBaseRule(
        code=code,
        natures=frozenset({ConceptNature.REMUNERATIVE}),
        minimum_parameter=minimum_parameter,
        maximum_parameter=maximum_parameter,
    )


def compute_tax_base(
    rule: TaxBaseRule,
    items: Iterable[ConceptResult | Mapping[str, Any]],
    parameters: Mapping[str, Any] | None = None,
) -> Decimal:
    """Compute one taxable base from calculated concepts.

    The function is pure: it does not mutate ``items`` or ``parameters`` and it never
    reads global state.  Missing parameters mean the corresponding limit is not
    applied.
    """

    params = parameters or {}
    raw = sum(
        (_item_amount(item) for item in items if item_matches_rule(rule, item)),
        start=Decimal("0"),
    )
    limited = apply_limits(raw, rule, params)
    if rule.rounding is not None:
        limited = quantize_base(limited, rule.rounding)
    return limited


def compute_tax_bases(
    rules: Mapping[str, TaxBaseRule] | Iterable[TaxBaseRule],
    items: Iterable[ConceptResult | Mapping[str, Any]],
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Decimal]:
    """Compute several bases and return ``{rule_code: amount}``.

    ``items`` is materialised once, so it is safe to pass a generator or queryset.
    Rules may be supplied as a mapping (for configuration keyed by code) or as any
    iterable of :class:`TaxBaseRule`.
    """

    materialised_items = list(items)
    if isinstance(rules, Mapping):
        rule_list = list(rules.values())
    else:
        rule_list = list(rules)

    result: dict[str, Decimal] = {}
    for rule in rule_list:
        if rule.code in result:
            raise TaxBaseError(f"duplicate tax base code {rule.code!r}")
        result[rule.code] = compute_tax_base(rule, materialised_items, parameters)
    return result


def taxable_codes(
    rule: TaxBaseRule,
    items: Iterable[ConceptResult | Mapping[str, Any]],
) -> list[str]:
    """Return the concept codes selected by a rule (useful for audit traces)."""

    return [_item_code(item) for item in filter_taxable_items(rule, items)]


__all__ = [
    "TaxBaseError",
    "TaxBaseRule",
    "apply_limits",
    "calculate_tax_base",
    "calculate_tax_bases",
    "compute_tax_base",
    "compute_tax_bases",
    "filter_taxable_items",
    "item_matches_rule",
    "quantize_base",
    "require_tax_base_limits",
    "taxable_codes",
]

# Short aliases kept for callers that prefer the "calculate" verb used by the
# calculator module.
calculate_tax_base = compute_tax_base
calculate_tax_bases = compute_tax_bases
