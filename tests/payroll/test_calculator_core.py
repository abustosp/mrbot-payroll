from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.core.payroll_engine.calculator import (
    CircularDependencyError,
    PayrollCalculationError,
    calculate_payroll,
)
from app.core.payroll_engine.types import (
    ConceptNature,
    FormulaDefinition,
    RoundingMode,
    RoundingPolicy,
)

PERIOD = date(2026, 6, 1)
EMPLOYEE = {
    "id": "EMP-1",
    "base_salary": Decimal("1000000"),
    "start_date": date(2021, 1, 1),
    "agreement_category": "Administrativo A",
    "workday_factor": Decimal("1"),
}


def remunerative(code: str, formula: dict, **kwargs) -> FormulaDefinition:
    return FormulaDefinition(
        code=code,
        description=code,
        formula=formula,
        nature=ConceptNature.REMUNERATIVE,
        **kwargs,
    )


def test_basic_salary_and_seniority_acceptance() -> None:
    definitions = [
        # Deliberately reversed: the resolver must impose the calculation order.
        remunerative(
            "ANTIGUEDAD",
            {
                "operator": "multiply",
                "arguments": [
                    {"concept": "SUELDO_BASICO"},
                    {"variable": "años_antiguedad"},
                    {"parameter": "porcentaje_antiguedad"},
                ],
            },
            depends_on=["SUELDO_BASICO"],
        ),
        remunerative("SUELDO_BASICO", {"variable": "sueldo_basico"}),
    ]

    result = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {"porcentaje_antiguedad": Decimal("0.01")},
    )

    by_code = {item.code: item for item in result.items}
    assert [item.code for item in result.items] == ["SUELDO_BASICO", "ANTIGUEDAD"]
    assert by_code["SUELDO_BASICO"].amount == Decimal("1000000.00")
    assert by_code["ANTIGUEDAD"].amount == Decimal("50000.00")
    assert result.remunerative == Decimal("1050000.00")
    assert result.non_remunerative == Decimal("0.00")
    assert result.gross == Decimal("1050000.00")
    assert result.net == Decimal("1050000.00")
    assert result.employer_cost == Decimal("1050000.00")
    assert result.employee_id == "EMP-1"
    assert result.period == PERIOD
    assert all(isinstance(item.amount, Decimal) for item in result.items)
    assert any(line.startswith("ANTIGUEDAD=50000.00") for line in result.trace)


def test_deduction_and_contribution_closing_rules() -> None:
    definitions = [
        remunerative("SUELDO_BASICO", {"variable": "sueldo_basico"}),
        FormulaDefinition(
            code="BONO_NO_REMUNERATIVO",
            description="Bono",
            formula={"parameter": "bono_no_remunerativo"},
            nature=ConceptNature.NON_REMUNERATIVE,
        ),
        FormulaDefinition(
            code="APORTE_JUBILACION",
            description="Aporte",
            formula={
                "operator": "multiply",
                "arguments": [
                    {"concept": "SUELDO_BASICO"},
                    {"parameter": "alicuota_aporte"},
                ],
            },
            depends_on=["SUELDO_BASICO"],
            nature=ConceptNature.DEDUCTION,
        ),
        FormulaDefinition(
            code="CONTRIBUCION_PATRONAL",
            description="Contribucion",
            formula={
                "operator": "multiply",
                "arguments": [
                    {"concept": "SUELDO_BASICO"},
                    {"parameter": "alicuota_contribucion"},
                ],
            },
            depends_on=["SUELDO_BASICO"],
            nature=ConceptNature.CONTRIBUTION,
        ),
        FormulaDefinition(
            code="AUXILIAR_BASE",
            description="Auxiliar",
            formula={"parameter": "auxiliar"},
            nature=ConceptNature.AUXILIARY,
        ),
    ]

    result = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {
            "bono_no_remunerativo": "100000",
            "alicuota_aporte": "0.11",
            "alicuota_contribucion": "0.20",
            "auxiliar": "999999",
        },
    )

    by_code = {item.code: item for item in result.items}
    assert by_code["APORTE_JUBILACION"].amount == Decimal("110000.00")
    assert by_code["CONTRIBUCION_PATRONAL"].amount == Decimal("200000.00")
    assert by_code["AUXILIAR_BASE"].amount == Decimal("999999.00")
    assert result.remunerative == Decimal("1000000.00")
    assert result.non_remunerative == Decimal("100000.00")
    assert result.deductions == Decimal("110000.00")
    assert result.contributions == Decimal("200000.00")
    assert result.gross == Decimal("1100000.00")
    assert result.net == Decimal("990000.00")
    assert result.employer_cost == Decimal("1300000.00")
    # Auxiliary and contributions never enter the net.
    assert result.net != result.gross - result.deductions - result.contributions
    assert result.net != Decimal("1200000.00")


def test_conditional_concept_is_zero_when_condition_not_met() -> None:
    definitions = [
        remunerative("SUELDO_BASICO", {"variable": "sueldo_basico"}),
        remunerative(
            "PRESENTISMO",
            {"constant": "80000"},
            conditions=[{"field": "presentismo", "operator": "greater_than", "value": 0}],
        ),
    ]

    with_bonus = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {"presentismo": "1"},
    )
    without_bonus = calculate_payroll(
        EMPLOYEE,
        PERIOD,
        definitions,
        {"presentismo": "0"},
    )

    assert with_bonus.gross == Decimal("1080000.00")
    assert without_bonus.gross == Decimal("1000000.00")
    presentismo = next(item for item in without_bonus.items if item.code == "PRESENTISMO")
    assert presentismo.amount == Decimal("0.00")
    assert "condition not met" in " ".join(presentismo.trace).lower()


def test_definition_rounding_policy_is_applied() -> None:
    definitions = [
        FormulaDefinition(
            code="AJUSTE",
            description="Ajuste con redondeo entero",
            formula={"constant": "100.5"},
            rounding=RoundingPolicy(decimals=0, mode=RoundingMode.HALF_UP),
            nature=ConceptNature.REMUNERATIVE,
        ),
        FormulaDefinition(
            code="AJUSTE_CENTAVOS",
            description="Ajuste a dos decimales",
            formula={"constant": "2.345"},
            rounding=RoundingPolicy(decimals=2, mode=RoundingMode.HALF_UP),
            nature=ConceptNature.REMUNERATIVE,
        ),
    ]

    result = calculate_payroll(EMPLOYEE, PERIOD, definitions, {})

    by_code = {item.code: item.amount for item in result.items}
    assert by_code["AJUSTE"] == Decimal("101")
    assert by_code["AJUSTE_CENTAVOS"] == Decimal("2.35")
    assert result.gross == Decimal("103.35")


def test_dependency_chain_is_ordered_regardless_of_input_order() -> None:
    definitions = [
        remunerative(
            "D",
            {
                "operator": "add",
                "arguments": [{"concept": "C"}, {"constant": "1"}],
            },
            depends_on=["C"],
        ),
        remunerative(
            "B",
            {
                "operator": "add",
                "arguments": [{"concept": "A"}, {"constant": "1"}],
            },
            depends_on=["A"],
        ),
        remunerative(
            "C",
            {
                "operator": "add",
                "arguments": [{"concept": "B"}, {"constant": "1"}],
            },
            depends_on=["B"],
        ),
        remunerative("A", {"constant": "10"}),
    ]

    result = calculate_payroll(EMPLOYEE, PERIOD, definitions, {})

    assert [item.code for item in result.items] == ["A", "B", "C", "D"]
    assert [item.amount for item in result.items] == [
        Decimal("10.00"),
        Decimal("11.00"),
        Decimal("12.00"),
        Decimal("13.00"),
    ]
    assert result.gross == Decimal("46.00")


def test_dependency_cycle_raises_clear_error() -> None:
    definitions = [
        remunerative(
            "A",
            {"operator": "add", "arguments": [{"concept": "B"}, {"constant": "1"}]},
            depends_on=["B"],
        ),
        remunerative(
            "B",
            {"operator": "add", "arguments": [{"concept": "A"}, {"constant": "1"}]},
            depends_on=["A"],
        ),
    ]

    with pytest.raises(CircularDependencyError) as exc_info:
        calculate_payroll(EMPLOYEE, PERIOD, definitions, {})

    message = str(exc_info.value).lower()
    assert "circular" in message or "cycle" in message
    assert "a" in message and "b" in message


def test_missing_dependency_is_reported() -> None:
    definitions = [
        remunerative(
            "ANTIGUEDAD",
            {"operator": "multiply", "arguments": [{"concept": "SUELDO_BASICO"}, {"constant": "1"}]},
        )
    ]

    with pytest.raises(PayrollCalculationError) as exc_info:
        calculate_payroll(EMPLOYEE, PERIOD, definitions, {})

    assert "missing formula dependency" in str(exc_info.value).lower()
    assert "SUELDO_BASICO" in str(exc_info.value)


def test_definitions_outside_validity_are_skipped() -> None:
    definitions = [
        remunerative(
            "SUELDO_BASICO",
            {"variable": "sueldo_basico"},
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        ),
        remunerative(
            "CONCEPTO_VIEJO",
            {"constant": "500"},
            valid_to=date(2025, 12, 31),
        ),
        remunerative(
            "CONCEPTO_FUTURO",
            {"constant": "700"},
            valid_from=date(2027, 1, 1),
        ),
    ]

    result = calculate_payroll(EMPLOYEE, PERIOD, definitions, {})

    assert [item.code for item in result.items] == ["SUELDO_BASICO"]
    assert result.gross == Decimal("1000000.00")
    assert any("skipped CONCEPTO_VIEJO" in line for line in result.trace)
    assert any("skipped CONCEPTO_FUTURO" in line for line in result.trace)


def test_employee_dataclass_is_supported() -> None:
    @dataclass
    class Employee:
        id: str
        base_salary: Decimal
        start_date: date
        agreement_category: str
        workday_factor: Decimal

    employee = Employee(
        id="EMP-2",
        base_salary=Decimal("800000"),
        start_date=date(2020, 3, 15),
        agreement_category="Administrativo B",
        workday_factor=Decimal("0.5"),
    )
    definitions = [
        remunerative("SUELDO_BASICO", {"variable": "base_salary"}),
        remunerative(
            "ANTIGUEDAD",
            {
                "operator": "multiply",
                "arguments": [
                    {"concept": "SUELDO_BASICO"},
                    {"variable": "antiguedad_anios"},
                    {"parameter": "porcentaje_antiguedad"},
                ],
            },
            depends_on=["SUELDO_BASICO"],
        ),
    ]

    result = calculate_payroll(
        employee,
        PERIOD,
        definitions,
        {"porcentaje_antiguedad": "0.01"},
    )

    assert result.employee_id == "EMP-2"
    assert result.items[0].amount == Decimal("800000.00")
    # 2020-03-15 to 2026-06-01 = 6 completed years.
    assert result.items[1].amount == Decimal("48000.00")
    assert result.gross == Decimal("848000.00")


def test_period_before_start_date_has_zero_seniority() -> None:
    employee = {**EMPLOYEE, "start_date": date(2026, 9, 1)}
    definitions = [
        remunerative(
            "ANTIGUEDAD",
            {
                "operator": "multiply",
                "arguments": [
                    {"variable": "sueldo_basico"},
                    {"variable": "antiguedad_anios"},
                    {"parameter": "porcentaje_antiguedad"},
                ],
            },
        )
    ]

    result = calculate_payroll(employee, PERIOD, definitions, {"porcentaje_antiguedad": "0.01"})
    assert result.items[0].amount == Decimal("0.00")


def test_invalid_employee_and_period_raise_clear_errors() -> None:
    definitions = [remunerative("SUELDO_BASICO", {"variable": "sueldo_basico"})]

    with pytest.raises(PayrollCalculationError, match="base_salary"):
        calculate_payroll({"id": "X"}, PERIOD, definitions, {})

    with pytest.raises(PayrollCalculationError, match="period"):
        calculate_payroll(EMPLOYEE, "2026-06-01", definitions, {})  # type: ignore[arg-type]


def test_empty_definitions_return_zeroed_result() -> None:
    result = calculate_payroll(EMPLOYEE, PERIOD, [], {})

    assert result.items == []
    assert result.gross == Decimal("0.00")
    assert result.net == Decimal("0.00")
    assert result.employer_cost == Decimal("0.00")
    assert result.period == PERIOD
