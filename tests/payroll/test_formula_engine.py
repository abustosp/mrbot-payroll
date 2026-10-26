from decimal import Decimal

import pytest

from app.core.payroll_engine.formula_engine import (
    FormulaError,
    evaluate_expression,
    evaluate_formula,
)
from app.core.payroll_engine.types import FormulaContext, FormulaDefinition, RoundingPolicy


def test_nested_decimal_formula_and_trace():
    definition = FormulaDefinition(
        code="ANTIGUEDAD",
        formula={
            "operator": "multiply",
            "arguments": [
                {"variable": "basico"},
                {"variable": "anios"},
                {"parameter": "porcentaje"},
            ],
        },
    )
    result = evaluate_formula(
        definition,
        FormulaContext(
            variables={"basico": Decimal("1000"), "anios": 5},
            parameters={"porcentaje": "0.01"},
        ),
    )
    assert result.value == Decimal("50.00")
    assert any("Input variable 'basico' = 1000" in line for line in result.trace)
    assert any("Rounded result" in line and "50.00" in line for line in result.trace)


def test_tree_defines_precedence_and_supports_nested_operations():
    expression = {
        "operator": "multiply",
        "arguments": [
            {"operator": "add", "arguments": [{"constant": "2"}, {"constant": "3"}]},
            {"constant": "4"},
        ],
    }
    assert evaluate_expression(expression, FormulaContext()).value == Decimal("20")


def test_false_condition_returns_rounded_zero_without_evaluating_formula():
    definition = FormulaDefinition(
        code="SOLO_CONDICIONAL",
        formula={"variable": "no_disponible"},
        conditions=[{"field": "anios", "operator": "greater_than", "value": 0}],
    )
    result = evaluate_formula(definition, FormulaContext(variables={"anios": 0}))
    assert result.value == Decimal("0.00")
    assert result.conditions_met is False


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("HALF_UP", Decimal("1.01")),
        ("HALF_EVEN", Decimal("1.00")),
        ("DOWN", Decimal("1.00")),
        ("UP", Decimal("1.01")),
    ],
)
def test_formula_rounding_modes(mode, expected):
    definition = FormulaDefinition(
        code="REDONDEO",
        formula={"constant": "1.005"},
        rounding=RoundingPolicy(decimals=2, mode=mode),
    )
    assert evaluate_formula(definition, FormulaContext()).value == expected


def test_percentage_is_a_times_b_over_one_hundred():
    result = evaluate_expression(
        {"operator": "percentage", "arguments": [{"constant": "1000"}, {"constant": "5"}]},
        FormulaContext(),
    )
    assert result.value == Decimal("50")


def test_division_by_zero_is_a_domain_error():
    with pytest.raises(FormulaError, match="division by zero"):
        evaluate_expression(
            {"operator": "divide", "arguments": [{"constant": "1"}, {"constant": "0"}]},
            FormulaContext(),
        )


@pytest.mark.parametrize(
    "expression",
    [
        {"operator": "__import__", "arguments": [{"constant": "os"}]},
        {"function": "__import__", "arguments": [{"constant": "os"}]},
        {"constant": "__import__('os').system('id')"},
        {"constant": "NaN"},
        {"constant": "Infinity"},
    ],
)
def test_injection_and_non_decimal_strings_are_rejected(expression):
    with pytest.raises(FormulaError):
        evaluate_expression(expression, FormulaContext())


def test_binary_float_is_rejected_even_when_supplied_as_context_input():
    with pytest.raises(FormulaError, match="float"):
        evaluate_expression({"variable": "importe"}, FormulaContext(variables={"importe": 0.1}))


def test_if_comparisons_and_boolean_operators():
    expression = {
        "operator": "if",
        "arguments": [
            {"operator": "and", "arguments": [
                {"operator": "gte", "arguments": [{"variable": "cantidad"}, {"constant": "2"}]},
                {"operator": "not", "arguments": [{"operator": "eq", "arguments": [{"constant": "0"}, {"constant": "1"}]}]},
            ]},
            {"constant": "10"},
            {"constant": "0"},
        ],
    }
    result = evaluate_expression(expression, FormulaContext(variables={"cantidad": "3"}))
    assert result.value == Decimal("10")
