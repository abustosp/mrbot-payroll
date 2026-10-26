from datetime import date
from decimal import Decimal

import pytest

from app.core.normative.parameters import (
    ParameterVersion,
    find_overlaps,
    select_parameter,
    validate_no_overlaps,
)
from app.jurisdictions.argentina.provider import ArgentinaProvider
from app.jurisdictions.argentina.validation import (
    is_valid_cuit_cuil,
    normalize_cuit_cuil,
    parse_period,
)


def parameter(code: str, value: str, start: date, end: date | None) -> ParameterVersion:
    return ParameterVersion(code, Decimal(value), start, end, source="test", version=1)


def test_parameter_selection_uses_inclusive_dates() -> None:
    values = [
        parameter("rate", "0.1", date(2026, 1, 1), date(2026, 6, 30)),
        parameter("rate", "0.2", date(2026, 7, 1), date(2026, 12, 31)),
    ]

    assert select_parameter(values, "rate", date(2026, 1, 1)).value == Decimal("0.1")
    assert select_parameter(values, "rate", date(2026, 6, 30)).value == Decimal("0.1")
    assert select_parameter(values, "rate", date(2026, 7, 1)).value == Decimal("0.2")
    assert select_parameter(values, "rate", date(2026, 12, 31)).value == Decimal("0.2")
    with pytest.raises(LookupError):
        select_parameter(values, "rate", date(2027, 1, 1))


def test_parameter_overlap_is_detected_inclusively() -> None:
    values = [
        parameter("rate", "0.1", date(2026, 1, 1), date(2026, 6, 30)),
        parameter("rate", "0.2", date(2026, 6, 30), date(2026, 12, 31)),
    ]

    assert len(find_overlaps(values)) == 1
    with pytest.raises(ValueError, match="overlapping versions"):
        validate_no_overlaps(values)
    with pytest.raises(ValueError, match="overlapping versions"):
        select_parameter(values, "rate", date(2026, 1, 1))


def test_demo_contributions_read_configured_versioned_rates() -> None:
    provider = ArgentinaProvider()
    contributions = provider.calculate_contributions(Decimal("100000"), "202606")

    assert contributions["employee"] == {
        "employee.retirement_rate": Decimal("11000.00"),
        "employee.pami_rate": Decimal("3000.00"),
        "employee.health_rate": Decimal("3000.00"),
    }
    assert contributions["employer"]["employer.retirement_rate"] == Decimal("10800.00")
    assert all(item.source == "demo-2026" for item in provider.parameters)


def test_demo_cct_scale_and_concepts_are_versioned_and_illustrative() -> None:
    provider = ArgentinaProvider()

    scale = provider.get_salary_scale("ADMIN_A", "202610")
    concepts = provider.calculate_cct_130_75(
        "ADMIN_A", "202610", seniority_years=Decimal("2")
    )

    assert scale.illustrative is True
    assert scale.source == "demo-2026"
    assert concepts["SUELDO_BASICO"] == Decimal("850000.00")
    assert concepts["ANTIGUEDAD"] == Decimal("17000.00")
    assert concepts["PRESENTISMO"] == Decimal("72221.10")
    with pytest.raises(LookupError):
        provider.get_salary_scale("ADMIN_A", "202701")


def test_income_tax_uses_versioned_progressive_brackets() -> None:
    provider = ArgentinaProvider()

    assert provider.calculate_income_tax(Decimal("2000000"), "202606") == Decimal("150000.00")
    assert all(bracket.source == "demo-2026" for bracket in provider.income_tax_brackets)
    with pytest.raises(LookupError):
        provider.calculate_income_tax(Decimal("2000000"), "202701")


def test_cuit_cuil_checksum_and_period_validation() -> None:
    assert normalize_cuit_cuil("30-00000000-7") == "30000000007"
    assert is_valid_cuit_cuil("20 00000000 1")
    assert not is_valid_cuit_cuil("30-00000000-8")
    assert not is_valid_cuit_cuil("３０000000007")
    assert parse_period("202602") == date(2026, 2, 1)
    with pytest.raises(ValueError, match="mes entre"):
        parse_period("202613")


def test_provider_validates_payroll_identifiers_and_period() -> None:
    errors = ArgentinaProvider().validate_payroll({
        "employer_cuit": "30-00000000-8",
        "period": "202613",
        "workers": [{"cuil": "20123456780"}],
    })

    assert len(errors) == 3
    assert any("CUIT empleador" in item for item in errors)
    assert any("Período" in item for item in errors)
    assert any("CUIL" in item for item in errors)
