from decimal import Decimal

import pytest

from app.core.payroll_engine.tax_bases import (
    TaxBaseError,
    TaxBaseRule,
    apply_limits,
    compute_tax_base,
    compute_tax_bases,
    filter_taxable_items,
    taxable_codes,
)
from app.core.payroll_engine.types import (
    ConceptNature,
    ConceptResult,
    RoundingMode,
    RoundingPolicy,
)


def item(code: str, nature: ConceptNature, amount: str) -> ConceptResult:
    return ConceptResult(code=code, name=code, nature=nature, amount=Decimal(amount))


ITEMS = [
    item("SUELDO_BASICO", ConceptNature.REMUNERATIVE, "1000"),
    item("ANTIGUEDAD", ConceptNature.REMUNERATIVE, "250"),
    item("BONO", ConceptNature.NON_REMUNERATIVE, "500"),
    item("APORTE", ConceptNature.DEDUCTION, "100"),
    item("CONTRIBUCION", ConceptNature.CONTRIBUTION, "200"),
    item("AUXILIAR", ConceptNature.AUXILIARY, "300"),
]


def test_default_base_uses_remunerative_concepts_only() -> None:
    rule = TaxBaseRule(code="REMUNERATIVA")
    assert compute_tax_base(rule, ITEMS) == Decimal("1250")
    assert taxable_codes(rule, ITEMS) == ["SUELDO_BASICO", "ANTIGUEDAD"]


def test_base_can_include_several_natures() -> None:
    rule = TaxBaseRule(
        code="REMUNERATIVA_Y_NO_REMUNERATIVA",
        natures=frozenset(
            {ConceptNature.REMUNERATIVE, ConceptNature.NON_REMUNERATIVE}
        ),
    )
    assert compute_tax_base(rule, ITEMS) == Decimal("1750")


def test_include_and_exclude_codes() -> None:
    only_basic = TaxBaseRule(
        code="SOLO_BASICO",
        include_codes=frozenset({"sueldo_basico"}),
    )
    assert compute_tax_base(only_basic, ITEMS) == Decimal("1000")

    without_antiguedad = TaxBaseRule(
        code="SIN_ANTIGUEDAD",
        exclude_codes=frozenset({"ANTIGUEDAD"}),
    )
    assert compute_tax_base(without_antiguedad, ITEMS) == Decimal("1000")
    assert taxable_codes(without_antiguedad, ITEMS) == ["SUELDO_BASICO"]

    filtered = filter_taxable_items(only_basic, ITEMS)
    assert [concept.code for concept in filtered] == ["SUELDO_BASICO"]


def test_minimum_and_cap_come_from_parameters() -> None:
    rule = TaxBaseRule(
        code="CON_TOPE",
        minimum_parameter="base_minima",
        maximum_parameter="base_maxima",
    )

    assert compute_tax_base(rule, ITEMS, {"base_minima": "1500", "base_maxima": "9000"}) == Decimal(
        "1500"
    )
    assert compute_tax_base(
        rule,
        [item("SUELDO_BASICO", ConceptNature.REMUNERATIVE, "10000")],
        {"base_minima": "1500", "base_maxima": "9000"},
    ) == Decimal("9000")
    # Missing parameters mean no limit is applied.
    assert compute_tax_base(rule, ITEMS, {}) == Decimal("1250")
    assert compute_tax_base(rule, ITEMS, {"base_minima": None}) == Decimal("1250")


def test_minimum_greater_than_maximum_is_rejected() -> None:
    rule = TaxBaseRule(
        code="INVALIDA",
        minimum_parameter="base_minima",
        maximum_parameter="base_maxima",
    )
    with pytest.raises(TaxBaseError, match="minimum"):
        compute_tax_base(rule, ITEMS, {"base_minima": "2000", "base_maxima": "1000"})


def test_negative_and_invalid_parameters_are_rejected() -> None:
    rule = TaxBaseRule(code="CON_MINIMO", minimum_parameter="base_minima")
    with pytest.raises(TaxBaseError, match="negative"):
        compute_tax_base(rule, ITEMS, {"base_minima": "-1"})
    with pytest.raises(TaxBaseError, match="decimal"):
        compute_tax_base(rule, ITEMS, {"base_minima": "no-numero"})


def test_base_rounding_policy() -> None:
    rule = TaxBaseRule(
        code="REDONDEADA",
        rounding=RoundingPolicy(decimals=0, mode=RoundingMode.HALF_UP),
    )
    items = [item("SUELDO_BASICO", ConceptNature.REMUNERATIVE, "100.5")]
    assert compute_tax_base(rule, items) == Decimal("101")


def test_multiple_bases_and_duplicates() -> None:
    rules = {
        "REM": TaxBaseRule(code="REM"),
        "NO_REM": TaxBaseRule(
            code="NO_REM",
            natures=frozenset({ConceptNature.NON_REMUNERATIVE}),
        ),
    }
    result = compute_tax_bases(rules, ITEMS)
    assert result == {"REM": Decimal("1250"), "NO_REM": Decimal("500")}

    duplicated = [TaxBaseRule(code="REM"), TaxBaseRule(code="REM")]
    with pytest.raises(TaxBaseError, match="duplicate"):
        compute_tax_bases(duplicated, ITEMS)


def test_apply_limits_is_pure_and_does_not_mutate_parameters() -> None:
    rule = TaxBaseRule(
        code="LIMITES",
        minimum_parameter="base_minima",
        maximum_parameter="base_maxima",
    )
    parameters = {"base_minima": "1500", "base_maxima": "9000"}
    snapshot = dict(parameters)
    assert apply_limits(Decimal("1250"), rule, parameters) == Decimal("1500")
    assert parameters == snapshot


def test_rule_validation() -> None:
    with pytest.raises(TaxBaseError, match="blank"):
        TaxBaseRule(code="  ")
    with pytest.raises(TaxBaseError, match="nature"):
        TaxBaseRule(code="X", natures=frozenset())
    with pytest.raises(TaxBaseError, match="blank minimum_parameter"):
        TaxBaseRule(code="X", minimum_parameter="  ")
