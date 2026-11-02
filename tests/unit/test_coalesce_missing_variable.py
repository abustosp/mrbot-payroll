from decimal import Decimal

import pytest

from app.core.payroll_engine.formula_engine import FormulaError, evaluate_expression
from app.core.payroll_engine.types import FormulaContext


def _ctx(**variables) -> FormulaContext:
    return FormulaContext(variables=variables)


COALESCE = {"operator": "coalesce", "arguments": [{"variable": "horas_extra"}, {"constant": 0}]}


def test_coalesce_uses_variable_when_present() -> None:
    assert evaluate_expression(COALESCE, _ctx(horas_extra=Decimal("5"))).value == Decimal("5")


def test_coalesce_treats_missing_variable_as_none() -> None:
    assert evaluate_expression(COALESCE, _ctx()).value == Decimal("0")


def test_plain_missing_variable_still_fails() -> None:
    with pytest.raises(FormulaError, match="missing variable"):
        evaluate_expression({"variable": "horas_extra"}, _ctx())
