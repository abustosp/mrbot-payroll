"""Initial Argentina jurisdiction provider with clearly marked demo data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.normative.parameters import ParameterStatus, ParameterVersion, select_parameters
from app.jurisdictions.argentina.rules import (
    IncomeTaxBracketVersion,
    calculate_contributions,
    calculate_income_tax,
    money,
)
from app.jurisdictions.argentina.validation import (
    normalize_cuit_cuil,
    parse_period,
    validate_period,
)

DEMO_FROM = date(2026, 1, 1)
DEMO_TO = date(2026, 12, 31)
DEMO_SOURCE = "demo-2026"


@dataclass(frozen=True, slots=True)
class AgreementCategory:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class SalaryScale:
    category_code: str
    monthly_salary: Decimal
    valid_from: date
    valid_to: date | None
    source: str = DEMO_SOURCE
    version: int = 1
    status: str = "demo"
    illustrative: bool = True


@dataclass(frozen=True, slots=True)
class PayrollRule:
    code: str
    description: str
    expression: str
    source: str = DEMO_SOURCE
    status: str = "demo"


ARGENTINA_CCT_130_75_CATEGORIES = (
    AgreementCategory("ADMIN_A", "Administrativo A"),
    AgreementCategory("ADMIN_B", "Administrativo B"),
    AgreementCategory("MAESTRANZA_A", "Maestranza A"),
    AgreementCategory("VENDEDOR_A", "Vendedor A"),
)

# Illustrative amounts only; replace this package with reviewed, approved sources.
ARGENTINA_CCT_130_75_SCALES = (
    SalaryScale("ADMIN_A", Decimal("850000.00"), DEMO_FROM, DEMO_TO),
    SalaryScale("ADMIN_B", Decimal("900000.00"), DEMO_FROM, DEMO_TO),
    SalaryScale("MAESTRANZA_A", Decimal("820000.00"), DEMO_FROM, DEMO_TO),
    SalaryScale("VENDEDOR_A", Decimal("870000.00"), DEMO_FROM, DEMO_TO),
)

ARGENTINA_CCT_130_75_RULES = (
    PayrollRule("SUELDO_BASICO", "Sueldo básico de escala", "escala.mensual"),
    PayrollRule(
        "ANTIGUEDAD",
        "Adicional de antigüedad ilustrativo",
        "basico * anios_antiguedad * parameter:cct13075.seniority_rate",
    ),
    PayrollRule(
        "PRESENTISMO",
        "Presentismo ilustrativo",
        "(basico + antiguedad) * parameter:cct13075.attendance_rate",
    ),
)


def _demo_parameters() -> tuple[ParameterVersion, ...]:
    rates = {
        "employee.retirement_rate": "0.11",
        "employee.pami_rate": "0.03",
        "employee.health_rate": "0.03",
        "employer.retirement_rate": "0.108",
        "employer.pami_rate": "0.02",
        "employer.health_rate": "0.06",
        "employer.family_allowance_rate": "0.047",
        "employer.employment_fund_rate": "0.015",
        "employer.work_risk_rate": "0.00",
        "cct13075.seniority_rate": "0.01",
        "cct13075.attendance_rate": "0.0833",
    }
    return tuple(
        ParameterVersion(
            code=code,
            value=Decimal(value),
            valid_from=DEMO_FROM,
            valid_to=DEMO_TO,
            published_at=DEMO_FROM,
            source=DEMO_SOURCE,
            version=1,
            status=ParameterStatus.DEMO,
        )
        for code, value in rates.items()
    )


def _demo_income_tax_brackets() -> tuple[IncomeTaxBracketVersion, ...]:
    # Demonstration brackets are intentionally not represented as legal rates.
    rows = (
        ("ganancias.demo.1", "0", "1000000", "0", "0.05"),
        ("ganancias.demo.2", "1000000", "2500000", "50000", "0.10"),
        ("ganancias.demo.3", "2500000", None, "200000", "0.15"),
    )
    return tuple(
        IncomeTaxBracketVersion(
            code=code,
            lower_limit=Decimal(lower),
            upper_limit=Decimal(upper) if upper is not None else None,
            fixed_amount=Decimal(fixed),
            rate=Decimal(rate),
            valid_from=DEMO_FROM,
            valid_to=DEMO_TO,
            published_at=DEMO_FROM,
            source=DEMO_SOURCE,
            version=1,
            status="demo",
        )
        for code, lower, upper, fixed, rate in rows
    )


class ArgentinaProvider:
    code = "AR"
    cct_code = "130/75"
    parameters: tuple[ParameterVersion, ...]
    income_tax_brackets: tuple[IncomeTaxBracketVersion, ...]
    categories: tuple[AgreementCategory, ...] = ARGENTINA_CCT_130_75_CATEGORIES
    salary_scales: tuple[SalaryScale, ...] = ARGENTINA_CCT_130_75_SCALES
    rules: tuple[PayrollRule, ...] = ARGENTINA_CCT_130_75_RULES

    def __init__(
        self,
        *,
        parameters: Sequence[ParameterVersion] | None = None,
        income_tax_brackets: Sequence[IncomeTaxBracketVersion] | None = None,
    ) -> None:
        self.parameters = tuple(parameters) if parameters is not None else _demo_parameters()
        self.income_tax_brackets = (
            tuple(income_tax_brackets)
            if income_tax_brackets is not None
            else _demo_income_tax_brackets()
        )

    def get_applicable_rules(self, employee_id: str, period: date) -> list[PayrollRule]:
        parse_period(period)
        return list(self.rules)

    def get_statutory_parameters(self, period: date) -> Mapping[str, Decimal]:
        effective_date = parse_period(period)
        return {
            code: version.value
            for code, version in select_parameters(self.parameters, effective_date).items()
        }

    def validate_payroll(self, payroll: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        try:
            normalize_cuit_cuil(payroll.get("employer_cuit"))
        except ValueError as exc:
            errors.append(f"CUIT empleador: {exc}")
        try:
            validate_period(payroll.get("period", ""))
        except (ValueError, TypeError) as exc:
            errors.append(f"Período: {exc}")
        workers = payroll.get("workers", ())
        if not isinstance(workers, Sequence) or isinstance(workers, (str, bytes)):
            errors.append("Trabajadores debe ser una secuencia.")
        else:
            for index, worker in enumerate(workers, start=1):
                try:
                    normalize_cuit_cuil(worker.get("cuil") if isinstance(worker, Mapping) else None)
                except ValueError as exc:
                    errors.append(f"Trabajador {index}, CUIL: {exc}")
        return errors

    def get_available_exports(self) -> tuple[str, ...]:
        return ("lsd_liquidation", "lsd_concepts")

    def get_salary_scale(self, category_code: str, period: date | str) -> SalaryScale:
        effective_date = parse_period(period)
        matches = [
            scale
            for scale in self.salary_scales
            if scale.category_code == category_code
            and scale.valid_from <= effective_date
            and (scale.valid_to is None or effective_date <= scale.valid_to)
        ]
        if not matches:
            raise LookupError(f"No hay escala para {category_code} en {effective_date:%Y%m}.")
        if len(matches) > 1:
            raise ValueError(f"Escalas superpuestas para {category_code} en {effective_date:%Y%m}.")
        return matches[0]

    def calculate_contributions(
        self, remunerative_base: Decimal, period: date | str
    ) -> dict[str, dict[str, Decimal]]:
        return calculate_contributions(remunerative_base, period, self.parameters)

    def calculate_income_tax(self, taxable_base: Decimal, period: date | str) -> Decimal:
        return calculate_income_tax(taxable_base, period, self.income_tax_brackets)

    def calculate_cct_130_75(
        self,
        category_code: str,
        period: date | str,
        *,
        seniority_years: Decimal = Decimal("0"),
        full_attendance: bool = True,
    ) -> dict[str, Decimal]:
        effective_date = parse_period(period)
        scale = self.get_salary_scale(category_code, effective_date)
        parameters = self.get_statutory_parameters(effective_date)
        basic = scale.monthly_salary
        seniority = money(
            basic * Decimal(str(seniority_years)) * parameters["cct13075.seniority_rate"]
        )
        attendance = (
            money((basic + seniority) * parameters["cct13075.attendance_rate"])
            if full_attendance
            else Decimal("0.00")
        )
        return {
            "SUELDO_BASICO": money(basic),
            "ANTIGUEDAD": seniority,
            "PRESENTISMO": attendance,
        }
