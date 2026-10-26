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


def parameter(
    code: str, value: str, start: date, end: date | None, status: object = "draft"
) -> ParameterVersion:
    return ParameterVersion(code, Decimal(value), start, end, source="test", version=1, status=status)  # type: ignore[arg-type]


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


def test_cct_presentismo_is_an_exact_twelfth() -> None:
    # B-06: Art. 40 DSL divides by 12; the 0.0833 demo rate underpaid $29.75
    # on a 892.500 base and must not come back.
    provider = ArgentinaProvider()
    concepts = provider.calculate_cct_130_75(
        "ADMIN_A", "202610", seniority_years=Decimal("2")
    )
    assert concepts["PRESENTISMO"] == Decimal("72250.00")
    assert "cct13075.attendance_rate" not in provider.get_statutory_parameters(
        date(2026, 10, 15)
    )


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
    assert concepts["PRESENTISMO"] == Decimal("72250.00")
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


def _approved_provider() -> ArgentinaProvider:
    from app.core.normative.parameters import ParameterStatus
    from app.jurisdictions.argentina.provider import (
        DEMO_FROM,
        DEMO_TO,
        SalaryScale,
    )
    from app.jurisdictions.argentina.rules import IncomeTaxBracketVersion

    rates = {
        "employee.retirement_rate": "0.11",
        "employee.pami_rate": "0.03",
        "employee.health_rate": "0.03",
        "employer.retirement_rate": "0.108",
        "employer.pami_rate": "0.02",
        "employer.health_rate": "0.06",
        "employer.family_allowance_rate": "0.047",
        "employer.employment_fund_rate": "0.015",
        "employer.work_risk_rate": "0.01",
        "cct13075.seniority_rate": "0.01",
    }
    parameters = tuple(
        parameter(code, value, DEMO_FROM, DEMO_TO, status=ParameterStatus.APPROVED)
        for code, value in rates.items()
    )
    brackets = (
        IncomeTaxBracketVersion(
            code="ganancias.test.1",
            lower_limit=Decimal("0"),
            upper_limit=None,
            fixed_amount=Decimal("0"),
            rate=Decimal("0.05"),
            valid_from=DEMO_FROM,
            valid_to=DEMO_TO,
            source="test",
            status="approved",
        ),
    )
    scales = (
        SalaryScale(
            "ADMIN_A", Decimal("1000.00"), DEMO_FROM, DEMO_TO,
            status="approved", illustrative=False,
        ),
    )
    return ArgentinaProvider(
        parameters=parameters, income_tax_brackets=brackets, salary_scales=scales
    )


def test_demo_provider_fails_explicitly_without_approved_data() -> None:
    # B-01/04/05 (mecanismo): sin datos aprobados el provider falla con la
    # lista de ofensores en vez de liquidar en silencio con demo.
    from app.jurisdictions.argentina.provider import UnapprovedDataError

    with pytest.raises(UnapprovedDataError) as excinfo:
        ArgentinaProvider().require_approved_data()
    message = str(excinfo.value)
    assert "ADMIN_A" in message
    assert "employer.work_risk_rate" in message
    assert "ganancias.demo.1" in message


def test_approved_provider_passes_and_demo_is_blocked_outside_dev() -> None:
    from app.jurisdictions.argentina.provider import UnapprovedDataError

    _approved_provider().require_approved_data()
    _approved_provider().assert_usable_in("production")
    ArgentinaProvider().assert_usable_in("development")
    with pytest.raises(UnapprovedDataError):
        ArgentinaProvider().assert_usable_in("production")


def test_tax_base_limits_fail_explicitly_without_approved_values() -> None:
    # B-03 (mecanismo): sin topes/pisos aprobados no se inventan valores (D-1).
    from app.core.payroll_engine.tax_bases import TaxBaseError, require_tax_base_limits

    with pytest.raises(TaxBaseError, match="base_maxima_remunerativa"):
        require_tax_base_limits({})
    rule = require_tax_base_limits({
        "base_minima_remunerativa": Decimal("100"),
        "base_maxima_remunerativa": Decimal("1000"),
    })
    assert rule.minimum_parameter == "base_minima_remunerativa"
    assert rule.maximum_parameter == "base_maxima_remunerativa"


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
