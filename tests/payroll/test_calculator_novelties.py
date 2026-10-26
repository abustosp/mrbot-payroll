from datetime import date
from decimal import Decimal

import pytest

from app.core.payroll_engine.calculator import calculate_payroll
from app.core.payroll_engine.concepts import (
    ConceptError,
    aggregate_novelties,
    normalize_novelties,
    normalize_novelty,
    novelty_variables,
    to_decimal,
)
from app.core.payroll_engine.types import ConceptNature, FormulaDefinition

PERIOD = date(2026, 6, 1)
EMPLOYEE = {
    "id": "EMP-N",
    "base_salary": "1000000",
    "start_date": date(2022, 1, 1),
    "agreement_category": "A",
    "workday_factor": "1",
}


def test_normalize_novelty_accepts_spanish_aliases() -> None:
    novelty = normalize_novelty(
        {
            "codigo": " horas_extra ",
            "cantidad": "10",
            "importe": 25000,
            "unidad": "horas",
            "tipo": "remunerativa",
        }
    )

    assert novelty.code == "horas_extra"
    assert novelty.quantity == Decimal("10")
    assert novelty.amount == Decimal("25000")
    assert novelty.unit == "horas"
    assert novelty.kind == "remunerativa"
    assert novelty.value == Decimal("25000")


def test_normalize_novelty_rejects_invalid_values() -> None:
    with pytest.raises(ConceptError, match="code"):
        normalize_novelty({"quantity": "1"})

    with pytest.raises(ConceptError, match="decimal"):
        normalize_novelty({"code": "BONO", "amount": "no-es-un-numero"})


def test_negative_novelty_values_are_allowed_for_adjustments() -> None:
    novelty = normalize_novelty({"code": "AJUSTE", "amount": "-1500.50"})
    assert novelty.value == Decimal("-1500.50")


def test_aggregate_novelties_sums_same_code_case_insensitively() -> None:
    novelties = [
        {"code": "horas_extra", "quantity": "4", "amount": "4000"},
        {"code": "HORAS_EXTRA", "quantity": "6", "amount": "6000"},
        {"code": "bono", "amount": "15000"},
    ]

    aggregated = aggregate_novelties(novelties)

    assert set(aggregated) == {"HORAS_EXTRA", "BONO"}
    assert aggregated["HORAS_EXTRA"].quantity == Decimal("10")
    assert aggregated["HORAS_EXTRA"].amount == Decimal("10000")
    # First spelling is preserved for display.
    assert aggregated["HORAS_EXTRA"].code == "horas_extra"

    quantities = novelty_variables(novelties)
    assert quantities["HORAS_EXTRA_CANTIDAD"] == Decimal("10")
    assert quantities["horas_extra_cantidad"] == Decimal("10")
    assert quantities["NOVEDAD_HORAS_EXTRA_IMPORTE"] == Decimal("10000")
    assert quantities["BONO"] == Decimal("15000")


def test_normalize_novelties_preserves_order_and_empty_input() -> None:
    assert normalize_novelties(None) == []
    assert normalize_novelties([]) == []
    result = normalize_novelties([{"code": "A"}, {"code": "B"}])
    assert [item.code for item in result] == ["A", "B"]
    assert result[0].value == Decimal("0")


def test_to_decimal_keeps_exact_values() -> None:
    assert to_decimal("1.1") == Decimal("1.1")
    assert to_decimal(1.1) == Decimal("1.1")
    assert to_decimal(5) == Decimal("5")
    assert to_decimal(None, allow_none=True) is None
    with pytest.raises(ConceptError, match="boolean"):
        to_decimal(True)
    with pytest.raises(ConceptError, match="finite"):
        to_decimal("NaN")


def test_calculator_uses_novelty_quantity_and_amount() -> None:
    definitions = [
        FormulaDefinition(
            code="SUELDO_BASICO",
            description="Basico",
            formula={"variable": "sueldo_basico"},
            nature=ConceptNature.REMUNERATIVE,
        ),
        FormulaDefinition(
            code="HORAS_EXTRA",
            description="Horas extra",
            formula={
                "operator": "multiply",
                "arguments": [
                    {"variable": "NOVEDAD_HORAS_EXTRA_CANTIDAD"},
                    {"parameter": "valor_hora_extra"},
                ],
            },
            nature=ConceptNature.REMUNERATIVE,
        ),
        FormulaDefinition(
            code="BONO",
            description="Bono no remunerativo",
            formula={"variable": "NOVEDAD_BONO_IMPORTE"},
            nature=ConceptNature.NON_REMUNERATIVE,
        ),
    ]
    novelties = [
        {"code": "horas_extra", "quantity": "4", "unit": "horas", "kind": "remunerativa"},
        {"code": "HORAS_EXTRA", "quantity": "6", "unit": "horas", "kind": "remunerativa"},
        {"code": "bono", "amount": "15000", "kind": "no_remunerativa"},
    ]

    result = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {"valor_hora_extra": "2500"},
        novelties,
    )

    by_code = {item.code: item for item in result.items}
    assert by_code["HORAS_EXTRA"].amount == Decimal("25000.00")
    assert by_code["BONO"].amount == Decimal("15000.00")
    assert result.remunerative == Decimal("1025000.00")
    assert result.non_remunerative == Decimal("15000.00")
    assert result.gross == Decimal("1040000.00")
    assert result.net == Decimal("1040000.00")


def test_calculator_exposes_quantity_as_value_when_amount_absent() -> None:
    definitions = [
        FormulaDefinition(
            code="VIATICOS",
            description="Viaticos",
            formula={"variable": "VIATICOS"},
            nature=ConceptNature.NON_REMUNERATIVE,
        )
    ]

    result = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {},
        [{"code": "viaticos", "quantity": "3", "unit": "dias"}],
    )

    assert result.items[0].amount == Decimal("3.00")
    assert result.non_remunerative == Decimal("3.00")
