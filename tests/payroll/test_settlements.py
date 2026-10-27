from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.payroll_engine.settlements import (
    FinalSettlementResult,
    SettlementInputError,
    SettlementParameterError,
    calculate_final_settlement,
    calculate_sac,
    calculate_vacations,
)
from app.core.payroll_engine.types import (
    ConceptNature,
    RoundingMode,
    RoundingPolicy,
)

PERIOD = date(2026, 6, 30)

PARAMETERS = {
    "preaviso_months": Decimal("1"),
    "month_integration_days_base": Decimal("30"),
    "vacation_days_base": Decimal("25"),
    "vacation_plus_rate": Decimal("0.20"),
    "seniority_months_per_year": Decimal("1"),
}

INPUTS = {
    "period": PERIOD,
    "monthly_salary": Decimal("1200000"),
    "integration_days": Decimal("15"),
    "vacation_days": Decimal("10"),
    "sac_months_worked": Decimal("6"),
    "sac_remunerations": [Decimal("1100000"), Decimal("1200000")],
    "years_of_service": Decimal("5"),
    "seniority_base_salary": Decimal("1200000"),
}


def test_sac_uses_best_remuneration_from_caller_supplied_window() -> None:
    result = calculate_sac(
        {
            date(2026, 1, 1): "1000000",
            date(2026, 2, 1): "1200000",
            date(2026, 3, 1): "1100000",
        },
        PERIOD,
        months_worked=Decimal("6"),
    )

    assert result.period == PERIOD
    assert result.base == Decimal("1200000")
    assert result.months_worked == Decimal("6")
    assert result.days_worked is None
    assert result.effective_months == Decimal("6")
    assert result.amount == Decimal("600000.00")
    assert any("best_salary=1200000" in line for line in result.trace)
    assert any("2026-02-01" in line for line in result.trace)
    assert any("semester window supplied by caller" in line for line in result.trace)


def test_sac_best_salary_override() -> None:
    result = calculate_sac(
        [],
        "2026-06-30",
        months_worked=Decimal("3"),
        best_salary="1200000",
    )

    assert result.base == Decimal("1200000")
    assert result.amount == Decimal("300000.00")
    assert any("explicit override" in line for line in result.trace)


def test_sac_proportional_months() -> None:
    result = calculate_sac(
        [Decimal("900000")],
        PERIOD,
        months_worked=Decimal("2"),
    )

    assert result.effective_months == Decimal("2")
    assert result.amount == Decimal("150000.00")


def test_sac_adds_day_fraction_to_months() -> None:
    result = calculate_sac(
        [Decimal("1200000")],
        PERIOD,
        months_worked=Decimal("2"),
        days_worked=Decimal("15"),
        days_base=Decimal("30"),
    )

    assert result.days_worked == Decimal("15")
    assert result.effective_months == Decimal("2.5")
    assert result.amount == Decimal("250000.00")
    assert any("days_worked=15/30=" in line for line in result.trace)


def test_sac_accepts_pure_day_proportion() -> None:
    result = calculate_sac(
        [Decimal("1200000")],
        PERIOD,
        months_worked=Decimal("0"),
        days_worked=Decimal("15"),
        days_base=Decimal("30"),
    )

    assert result.effective_months == Decimal("0.5")
    assert result.amount == Decimal("50000.00")


def test_sac_zero_months_returns_zero_without_remunerations() -> None:
    result = calculate_sac([], PERIOD, months_worked=Decimal("0"))

    assert result.base == Decimal("0")
    assert result.amount == Decimal("0.00")
    assert any("no accrual" in line for line in result.trace)


def test_sac_empty_remunerations_without_override_is_an_error() -> None:
    with pytest.raises(SettlementInputError, match="empty"):
        calculate_sac([], PERIOD, months_worked=Decimal("1"))


def test_sac_day_proration_requires_days_base() -> None:
    with pytest.raises(SettlementParameterError, match="days_base"):
        calculate_sac(
            [Decimal("1200000")],
            PERIOD,
            months_worked=Decimal("0"),
            days_worked=Decimal("15"),
        )


def test_sac_rounds_half_up_to_two_decimals() -> None:
    result = calculate_sac([Decimal("100")], PERIOD, months_worked=Decimal("0.5"))

    assert result.amount == Decimal("4.17")


def test_sac_rejects_float_inputs() -> None:
    with pytest.raises(SettlementInputError, match="float"):
        calculate_sac([1000.0], PERIOD, months_worked=Decimal("6"))


def test_vacations_base_calculation() -> None:
    result = calculate_vacations(Decimal("750000"), Decimal("10"))

    assert result.days_base == Decimal("25")
    assert result.plus_rate == Decimal("0")
    assert result.daily_value == Decimal("30000")
    assert result.base_amount == Decimal("300000.00")
    assert result.plus_amount == Decimal("0.00")
    assert result.amount == Decimal("300000.00")


def test_vacations_plus_is_configurable() -> None:
    result = calculate_vacations(
        "750000",
        "10",
        days_base=Decimal("25"),
        plus_rate=Decimal("0.20"),
    )

    assert result.daily_value == Decimal("30000")
    assert result.base_amount == Decimal("300000.00")
    assert result.plus_amount == Decimal("60000.00")
    assert result.amount == Decimal("360000.00")


def test_vacations_zero_days_returns_zero() -> None:
    result = calculate_vacations(
        Decimal("750000"),
        Decimal("0"),
        days_base=Decimal("25"),
        plus_rate=Decimal("0.20"),
    )

    assert result.daily_value == Decimal("30000")
    assert result.base_amount == Decimal("0.00")
    assert result.plus_amount == Decimal("0.00")
    assert result.amount == Decimal("0.00")


def test_vacations_rounding_is_half_up() -> None:
    result = calculate_vacations(
        Decimal("0.15"),
        Decimal("1"),
        days_base=Decimal("30"),
    )

    assert result.daily_value == Decimal("0.005")
    assert result.base_amount == Decimal("0.01")
    assert result.amount == Decimal("0.01")


def test_vacations_reject_zero_days_base() -> None:
    with pytest.raises(SettlementParameterError, match="days_base"):
        calculate_vacations(Decimal("750000"), Decimal("10"), days_base=0)


def test_vacations_reject_negative_days() -> None:
    with pytest.raises(SettlementInputError, match="cannot be negative"):
        calculate_vacations(Decimal("750000"), Decimal("-1"))


def test_final_settlement_complete_case() -> None:
    result = calculate_final_settlement(INPUTS, PARAMETERS)

    assert isinstance(result, FinalSettlementResult)
    assert result.period == PERIOD
    assert [item.code for item in result.items] == [
        "PREAVISO",
        "INTEGRACION_MES",
        "VACACIONES_NO_GOZADAS",
        "SAC_PROPORCIONAL",
        "INDEMNIZACION_ANTIGUEDAD",
    ]

    by_code = {item.code: item for item in result.items}
    assert by_code["PREAVISO"].amount == Decimal("1200000.00")
    assert by_code["INTEGRACION_MES"].amount == Decimal("600000.00")
    assert by_code["VACACIONES_NO_GOZADAS"].amount == Decimal("576000.00")
    assert by_code["SAC_PROPORCIONAL"].amount == Decimal("600000.00")
    assert by_code["INDEMNIZACION_ANTIGUEDAD"].amount == Decimal("6000000.00")
    assert by_code["INDEMNIZACION_ANTIGUEDAD"].nature == ConceptNature.NON_REMUNERATIVE
    assert all(
        item.nature == ConceptNature.REMUNERATIVE
        for code, item in by_code.items()
        if code != "INDEMNIZACION_ANTIGUEDAD"
    )

    assert result.total == Decimal("8976000.00")
    assert result.remunerative_total == Decimal("2976000.00")
    assert result.non_remunerative_total == Decimal("6000000.00")
    assert all(item.amount.as_tuple().exponent == -2 for item in result.items)
    assert any("final settlement period=2026-06-30" in line for line in result.trace)
    assert any(line.startswith("PREAVISO: formula=") for line in result.trace)
    assert any(line.startswith("VACACIONES_NO_GOZADAS: daily_value=") for line in result.trace)


def test_final_settlement_zero_components() -> None:
    inputs = {
        **INPUTS,
        "integration_days": Decimal("0"),
        "vacation_days": Decimal("0"),
        "sac_months_worked": Decimal("0"),
        "sac_remunerations": [],
        "years_of_service": Decimal("0"),
    }

    result = calculate_final_settlement(
        inputs,
        {**PARAMETERS, "preaviso_months": Decimal("0")},
    )

    assert all(item.amount == Decimal("0.00") for item in result.items)
    assert result.total == Decimal("0.00")
    assert result.remunerative_total == Decimal("0.00")
    assert result.non_remunerative_total == Decimal("0.00")
    assert len(result.items) == 5


def test_final_settlement_uses_explicit_seniority_base() -> None:
    inputs = {
        **INPUTS,
        "monthly_salary": Decimal("1000000"),
        "seniority_base_salary": Decimal("900000"),
    }

    result = calculate_final_settlement(inputs, PARAMETERS)
    seniority = next(item for item in result.items if item.code == "INDEMNIZACION_ANTIGUEDAD")

    assert seniority.amount == Decimal("4500000.00")


@pytest.mark.parametrize(
    "parameter",
    [
        "preaviso_months",
        "month_integration_days_base",
        "vacation_days_base",
        "vacation_plus_rate",
        "seniority_months_per_year",
    ],
)
def test_final_settlement_requires_each_parameter(parameter: str) -> None:
    parameters = dict(PARAMETERS)
    parameters.pop(parameter)

    with pytest.raises(SettlementParameterError, match=parameter):
        calculate_final_settlement(INPUTS, parameters)


@pytest.mark.parametrize(
    "input_name",
    [
        "period",
        "monthly_salary",
        "integration_days",
        "vacation_days",
        "sac_months_worked",
        "years_of_service",
        "seniority_base_salary",
    ],
)
def test_final_settlement_requires_each_input(input_name: str) -> None:
    inputs = dict(INPUTS)
    inputs.pop(input_name)

    with pytest.raises(SettlementInputError, match=input_name):
        calculate_final_settlement(inputs, PARAMETERS)


def test_final_settlement_requires_sac_days_base_only_when_days_are_used() -> None:
    inputs = {
        **INPUTS,
        "sac_months_worked": Decimal("0"),
        "sac_days_worked": Decimal("15"),
    }

    with pytest.raises(SettlementParameterError, match="sac_days_base"):
        calculate_final_settlement(inputs, PARAMETERS)

    result = calculate_final_settlement(
        inputs,
        {**PARAMETERS, "sac_days_base": Decimal("30")},
    )
    sac = next(item for item in result.items if item.code == "SAC_PROPORCIONAL")

    assert sac.quantity == Decimal("0.5")
    assert sac.amount == Decimal("50000.00")


def test_final_settlement_rejects_float_parameters() -> None:
    with pytest.raises(SettlementParameterError, match="float"):
        calculate_final_settlement(
            INPUTS,
            {**PARAMETERS, "vacation_plus_rate": 0.20},
        )


def test_final_settlement_accepts_custom_rounding_policy() -> None:
    policy = RoundingPolicy(decimals=0, mode=RoundingMode.DOWN)

    result = calculate_final_settlement(INPUTS, PARAMETERS, rounding=policy)

    assert all(item.amount.as_tuple().exponent == 0 for item in result.items)
    assert result.total == Decimal("8976000")


def test_sac_rejects_more_than_six_remunerations() -> None:
    """B-28: seven monthly pays in the window inflate the SAC (+16,7 %)."""

    with pytest.raises(SettlementInputError, match="at most 6"):
        calculate_sac(
            [Decimal("1000000")] * 7, PERIOD, months_worked=Decimal("6")
        )


def test_sac_rejects_effective_months_beyond_semester() -> None:
    """B-28: accrual beyond the six months of a semester is rejected."""

    with pytest.raises(SettlementInputError, match="exceeds"):
        calculate_sac([Decimal("1000000")], PERIOD, months_worked=Decimal("7"))
    with pytest.raises(SettlementInputError, match="exceeds"):
        calculate_sac(
            [Decimal("1000000")],
            PERIOD,
            months_worked=Decimal("6"),
            days_worked=Decimal("15"),
            days_base=Decimal("30"),
        )


def test_vacations_missing_plus_rate_warns_but_keeps_amounts() -> None:
    """B-29: an omitted plus_rate liquidates zero plus with a warning."""

    result = calculate_vacations(Decimal("750000"), Decimal("10"))

    assert result.plus_rate == Decimal("0")
    assert result.plus_amount == Decimal("0.00")
    assert result.amount == Decimal("300000.00")
    assert any("plus_rate" in warning for warning in result.warnings)


def test_vacations_explicit_zero_plus_rate_warns() -> None:
    """B-29R: an explicit zero also warns (the CCT default stays pending D-6)."""

    result = calculate_vacations(Decimal("750000"), Decimal("10"), plus_rate=Decimal("0"))

    assert result.plus_amount == Decimal("0.00")
    assert any("plus_rate" in warning for warning in result.warnings)


def test_vacations_sequential_rounding_is_pinned() -> None:
    """B-34: current policy (base, plus, total) pinned pending D-6."""

    result = calculate_vacations(
        Decimal("1000"), Decimal("1"),
        days_base=Decimal("30"), plus_rate=Decimal("0.10"),
    )

    assert result.base_amount == Decimal("33.33")
    assert result.plus_amount == Decimal("3.33")
    assert result.amount == Decimal("36.66")


def test_settlement_period_accepts_aaaamm_like_the_provider() -> None:
    """B-78: the same period string is valid in settlements and provider."""

    from app.jurisdictions.argentina.validation import parse_period

    result = calculate_sac(
        [Decimal("1000000")], "202606", months_worked=Decimal("6")
    )

    assert result.period == date(2026, 6, 1)
    assert parse_period("202606") == result.period
