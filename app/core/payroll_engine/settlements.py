"""Deterministic SAC, vacation and final-settlement calculations.

This module is deliberately a pure calculation layer.  It does not decide which
months belong to a SAC semester, which notice period is legally applicable or
which indemnification scale a collective agreement mandates.  Those rules arrive
as explicit inputs (employee data) or parameters (normative configuration).

Formulas
--------
SAC::

    base = max(remunerations) or explicit best_salary
    effective_months = months_worked + days_worked / days_base
    amount = base / 12 * effective_months

Vacations::

    daily_value = monthly_salary / days_base
    base_amount = daily_value * days
    plus_amount = base_amount * plus_rate
    amount = base_amount + plus_amount

Final settlement components::

    preaviso = monthly_salary * preaviso_months
    integration = monthly_salary / integration_days_base * integration_days
    vacations = calculate_vacations(...)
    sac = calculate_sac(...)
    seniority = seniority_base_salary * years * seniority_months_per_year

Missing parameters raise :class:`SettlementParameterError`; this module never
falls back to a statutory value.  Inputs are converted to ``Decimal`` and binary
floats are rejected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.payroll_engine.rounding import quantize, to_decimal
from app.core.payroll_engine.types import ConceptNature, RoundingMode, RoundingPolicy
from app.jurisdictions.argentina.validation import parse_period

SETTLEMENT_ROUNDING = RoundingPolicy(decimals=2, mode=RoundingMode.HALF_UP)
SAC_DIVISOR = Decimal("12")
# B-28: a SAC semester holds at most six monthly remunerations / six months.
SAC_SEMESTER_MONTHS = Decimal("6")
SAC_SEMESTER_COUNT = 6
ZERO = Decimal("0")

Numeric = Decimal | int | str


class SettlementError(ValueError):
    """Base class for deterministic settlement errors."""


class SettlementInputError(SettlementError):
    """Raised when an input value is missing, invalid or out of range."""


class SettlementParameterError(SettlementError):
    """Raised when a required normative parameter is missing or invalid."""


@dataclass(slots=True)
class SacResult:
    """Result of a SAC accrual calculation."""

    period: date
    base: Decimal
    months_worked: Decimal
    days_worked: Decimal | None
    effective_months: Decimal
    amount: Decimal
    trace: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VacationResult:
    """Result of a vacation pay calculation."""

    monthly_salary: Decimal
    days: Decimal
    days_base: Decimal
    daily_value: Decimal
    plus_rate: Decimal
    base_amount: Decimal
    plus_amount: Decimal
    amount: Decimal
    trace: list[str] = field(default_factory=list)
    # B-29: non-blocking warnings (e.g. plus_rate taken as 0 by omission).
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SettlementItem:
    """One separately reported component of a final settlement."""

    code: str
    name: str
    nature: ConceptNature
    amount: Decimal
    quantity: Decimal | None = None
    unit: str | None = None
    trace: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FinalSettlementResult:
    """Final settlement with independently calculated components and totals."""

    period: date
    items: list[SettlementItem]
    total: Decimal
    remunerative_total: Decimal
    non_remunerative_total: Decimal
    trace: list[str] = field(default_factory=list)


def _format(value: Decimal) -> str:
    """Render a Decimal without exponent notation for audit traces."""

    return format(value, "f")


def _as_decimal(
    value: Any,
    *,
    field_name: str,
    error_type: type[SettlementError],
) -> Decimal:
    try:
        return to_decimal(value)
    except ValueError as exc:
        raise error_type(f"{field_name}: {exc}") from exc


def _non_negative(
    value: Any,
    *,
    field_name: str,
    error_type: type[SettlementError],
) -> Decimal:
    result = _as_decimal(value, field_name=field_name, error_type=error_type)
    if result < ZERO:
        raise error_type(f"{field_name} cannot be negative")
    return result


def _positive(
    value: Any,
    *,
    field_name: str,
    error_type: type[SettlementError],
) -> Decimal:
    result = _as_decimal(value, field_name=field_name, error_type=error_type)
    if result <= ZERO:
        raise error_type(f"{field_name} must be greater than zero")
    return result


def _coerce_period(value: Any) -> date:
    # B-78: settlement dates share the single payroll period parser, so the
    # same period is valid here and in the jurisdiction provider (AAAAMM
    # resolves to the first day of the month; a full ISO date keeps its day).
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return parse_period(value)
        except ValueError as exc:
            raise SettlementInputError(f"period: {exc}") from exc
    raise SettlementInputError(f"period must be a date, got {type(value).__name__}")


def _required_input(inputs: Mapping[str, Any], name: str) -> Any:
    if name not in inputs or inputs[name] is None:
        raise SettlementInputError(f"missing required final-settlement input {name!r}")
    return inputs[name]


def _required_parameter(
    parameters: Mapping[str, Any],
    name: str,
    *,
    allow_zero: bool,
) -> Decimal:
    if name not in parameters or parameters[name] is None:
        raise SettlementParameterError(
            f"missing required parameter {name!r}; no legal default is applied"
        )
    if allow_zero:
        return _non_negative(
            parameters[name],
            field_name=f"parameter {name!r}",
            error_type=SettlementParameterError,
        )
    return _positive(
        parameters[name],
        field_name=f"parameter {name!r}",
        error_type=SettlementParameterError,
    )


def _normalise_remunerations(
    remunerations: Iterable[Numeric] | Mapping[Any, Numeric] | None,
) -> tuple[list[Decimal], list[Any]]:
    """Return exact remuneration values and the label of each value."""

    if remunerations is None:
        return [], []
    if isinstance(remunerations, Mapping):
        labels = list(remunerations.keys())
        raw_values = list(remunerations.values())
    elif isinstance(remunerations, (str, bytes)):
        raise SettlementInputError("'remunerations' must be a sequence of amounts, not a string")
    else:
        try:
            raw_values = list(remunerations)
        except TypeError as exc:
            raise SettlementInputError("'remunerations' must be an iterable of amounts") from exc
        labels = list(range(len(raw_values)))

    values: list[Decimal] = []
    for index, raw_value in enumerate(raw_values):
        values.append(
            _non_negative(
                raw_value,
                field_name=f"remuneration[{labels[index]!r}]",
                error_type=SettlementInputError,
            )
        )
    return values, labels


def calculate_sac(
    remunerations: Iterable[Numeric] | Mapping[Any, Numeric] | None,
    period: date | str,
    *,
    months_worked: Numeric,
    best_salary: Numeric | None = None,
    days_worked: Numeric | None = None,
    days_base: Numeric | None = None,
    rounding: RoundingPolicy = SETTLEMENT_ROUNDING,
) -> SacResult:
    """Calculate SAC (aguinaldo) from the best remuneration of the period.

    The caller decides the semester window and supplies the remunerations that
    belong to it.  ``months_worked`` is the number of accrual months already
    determined by the applicable rule; it is not capped or inferred here.  When
    ``days_worked`` is supplied, it is added as a fraction of ``days_base`` (for
    example ``months_worked=2`` plus ``days_worked=15`` over ``days_base=30``
    yields ``2.5`` effective months).  ``best_salary`` overrides the maximum of
    ``remunerations`` when the applicable rule uses another base.

    Args:
        remunerations: Semester remunerations, either an iterable of amounts or
            a mapping whose keys are used in the trace (for example period dates).
        period: SAC period used for traceability.
        months_worked: Accrual months, exact and non-negative.
        best_salary: Optional explicit base instead of ``max(remunerations)``.
        days_worked: Optional additional days for proportional accrual.
        days_base: Days in the month used for day proration; required with
            ``days_worked`` and never defaulted.
        rounding: Money rounding policy, two decimals HALF_UP by default.

    Raises:
        SettlementInputError: For invalid or insufficient input data,
            including a semester window larger than 6 remunerations or
            6 effective months (B-28; the window itself stays caller-owned).
        SettlementParameterError: When day proration lacks ``days_base``.
    """

    effective_period = _coerce_period(period)
    months = _non_negative(
        months_worked,
        field_name="months_worked",
        error_type=SettlementInputError,
    )

    trace = [
        f"SAC period={effective_period.isoformat()}",
        "semester window supplied by caller; not inferred from the calendar",
    ]

    days: Decimal | None = None
    effective_months = months
    # B-28: the caller assembles the semester, but the semester size is a
    # domain invariant: more than 6 remunerations or 6 effective months
    # inflates the SAC instead of failing (which semester the months belong
    # to is still the caller's call; see D-9).
    if isinstance(remunerations, Mapping):
        window_size = len(remunerations)
    elif remunerations is None or isinstance(remunerations, (str, bytes)):
        window_size = 0
    else:
        # Materialised once so generators are not exhausted before use below.
        remunerations = list(remunerations)
        window_size = len(remunerations)
    if window_size > SAC_SEMESTER_COUNT:
        raise SettlementInputError(
            f"'remunerations' has {window_size} entries; "
            f"a SAC semester holds at most {SAC_SEMESTER_COUNT}"
        )
    if days_worked is not None:
        if days_base is None:
            raise SettlementParameterError(
                "missing required parameter 'days_base' for SAC day proration; "
                "no legal default is applied"
            )
        days = _non_negative(
            days_worked,
            field_name="days_worked",
            error_type=SettlementInputError,
        )
        base_days = _positive(
            days_base,
            field_name="days_base",
            error_type=SettlementParameterError,
        )
        day_fraction = days / base_days
        effective_months = months + day_fraction
        trace.append(
            f"days_worked={_format(days)}/{_format(base_days)}={_format(day_fraction)} months"
        )
        trace.append(
            f"effective_months={_format(effective_months)} "
            f"({_format(months)} months + day fraction)"
        )
    else:
        trace.append(f"months_worked={_format(months)}")

    if effective_months > SAC_SEMESTER_MONTHS:
        raise SettlementInputError(
            f"effective_months={_format(effective_months)} exceeds "
            f"the {SAC_SEMESTER_MONTHS} months of a SAC semester"
        )

    if best_salary is not None:
        base = _non_negative(
            best_salary,
            field_name="best_salary",
            error_type=SettlementInputError,
        )
        trace.append(f"best_salary={_format(base)} (explicit override)")
    else:
        values, labels = _normalise_remunerations(remunerations)
        if values:
            base = max(values)
            best_index = values.index(base)
            trace.append(
                f"remunerations={len(values)}; best_salary={_format(base)} "
                f"from {labels[best_index]}"
            )
        elif effective_months == ZERO:
            base = ZERO
            trace.append("remunerations empty; no accrual because effective_months=0")
        else:
            raise SettlementInputError(
                "'remunerations' is empty and 'best_salary' was not provided"
            )

    amount = quantize(base / SAC_DIVISOR * effective_months, rounding)
    trace.append(
        f"formula=best_salary / 12 * effective_months = "
        f"{_format(base)} / 12 * {_format(effective_months)}"
    )
    trace.append(f"amount={_format(amount)}")

    return SacResult(
        period=effective_period,
        base=base,
        months_worked=months,
        days_worked=days,
        effective_months=effective_months,
        amount=amount,
        trace=trace,
    )


def calculate_vacations(
    monthly_salary: Numeric,
    days: Numeric,
    *,
    days_base: Numeric = 25,
    plus_rate: Numeric | None = None,
    rounding: RoundingPolicy = SETTLEMENT_ROUNDING,
) -> VacationResult:
    """Calculate vacation pay for a number of days.

    The daily value is ``monthly_salary / days_base`` and the optional plus is a
    fraction of the base amount (``0.20`` means a 20 % plus).  ``days_base`` and
    ``plus_rate`` are explicit arguments so a collective agreement can override
    the API defaults.

    B-34 (pinned pending D-6): rounding is sequential — ``base_amount`` is
    quantized, then ``plus_amount`` is computed over the rounded base and
    quantized, then the total is quantized (each step ``decimals=2 HALF_UP``
    by default).  With salary 1000, 1 day, base 30 and a 10 % plus this gives
    33.33 + 3.33 = 36.66, one cent below single rounding (36.67).  Changing
    this policy is a legal decision (D-6), not a code fix.

    B-29: ``plus_rate=None`` (omitted) liquidates a zero plus with a warning;
    pass ``0`` explicitly when no plus applies.
    """

    salary = _non_negative(
        monthly_salary,
        field_name="monthly_salary",
        error_type=SettlementInputError,
    )
    day_count = _non_negative(
        days,
        field_name="days",
        error_type=SettlementInputError,
    )
    base_days = _positive(
        days_base,
        field_name="days_base",
        error_type=SettlementParameterError,
    )
    warnings: list[str] = []
    if plus_rate is None:
        rate = ZERO
        warnings.append(
            "plus_rate no especificado: se liquida plus 0; "
            "verificar si el CCT exige plus vacacional (ver D-6)"
        )
    else:
        rate = _non_negative(
            plus_rate,
            field_name="plus_rate",
            error_type=SettlementParameterError,
        )
        # B-29: un plus 0 explícito también avisa: declara que no corresponde
        # plus, pero el default por CCT sigue pendiente (ver D-6).
        if rate == ZERO:
            warnings.append(
                "plus_rate 0 explícito: se liquida plus 0; "
                "verificar si el CCT exige plus vacacional (ver D-6)"
            )

    daily_value = salary / base_days
    base_amount = quantize(daily_value * day_count, rounding)
    plus_amount = quantize(base_amount * rate, rounding)
    amount = quantize(base_amount + plus_amount, rounding)

    trace = [
        f"monthly_salary={_format(salary)}",
        f"daily_value={_format(salary)}/{_format(base_days)}={_format(daily_value)}",
        f"base_amount={_format(daily_value)}*{_format(day_count)}={_format(base_amount)}",
        f"plus_rate={_format(rate)}; plus_amount={_format(base_amount)}*"
        f"{_format(rate)}={_format(plus_amount)}",
        f"amount={_format(base_amount)}+{_format(plus_amount)}={_format(amount)}",
    ]
    trace.extend(f"warning: {warning}" for warning in warnings)

    return VacationResult(
        monthly_salary=salary,
        days=day_count,
        days_base=base_days,
        daily_value=daily_value,
        plus_rate=rate,
        base_amount=base_amount,
        plus_amount=plus_amount,
        amount=amount,
        trace=trace,
        warnings=warnings,
    )


def calculate_final_settlement(
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    rounding: RoundingPolicy = SETTLEMENT_ROUNDING,
) -> FinalSettlementResult:
    """Calculate a final settlement as independent components.

    Required ``inputs`` keys:

    - ``period``: settlement date (``date`` or ISO string).
    - ``monthly_salary``: monthly salary used by notice, month integration and
      vacations.
    - ``integration_days``: days of the termination month to integrate.
    - ``vacation_days``: unused vacation days.
    - ``sac_months_worked``: SAC accrual months already determined by the rule.
    - ``years_of_service``: service years used by the seniority indemnification.
    - ``seniority_base_salary``: explicit salary base for the indemnification.
    - ``sac_remunerations`` (optional): semester remunerations for proportional
      SAC; ``sac_best_salary`` may replace them.
    - ``sac_days_worked`` (optional): extra SAC accrual days.

    Required ``parameters`` keys (there are no legal defaults):

    - ``preaviso_months``: notice months expressed as monthly salaries.
    - ``month_integration_days_base``: days base for month integration.
    - ``vacation_days_base``: days base for vacation pay.
    - ``vacation_plus_rate``: vacation plus rate as a fraction; use ``0``
      explicitly when no plus applies.
    - ``seniority_months_per_year``: monthly salaries per year of service.
    - ``sac_days_base``: only when ``sac_days_worked`` is supplied.

    Item natures are reporting labels for downstream consumers; this function
    does not calculate contributions, deductions or taxable bases.
    """

    if not isinstance(inputs, Mapping):
        raise SettlementInputError("inputs must be a mapping")
    if not isinstance(parameters, Mapping):
        raise SettlementParameterError("parameters must be a mapping")

    effective_period = _coerce_period(_required_input(inputs, "period"))
    monthly_salary = _non_negative(
        _required_input(inputs, "monthly_salary"),
        field_name="monthly_salary",
        error_type=SettlementInputError,
    )
    integration_days = _non_negative(
        _required_input(inputs, "integration_days"),
        field_name="integration_days",
        error_type=SettlementInputError,
    )
    vacation_days = _non_negative(
        _required_input(inputs, "vacation_days"),
        field_name="vacation_days",
        error_type=SettlementInputError,
    )
    sac_months = _non_negative(
        _required_input(inputs, "sac_months_worked"),
        field_name="sac_months_worked",
        error_type=SettlementInputError,
    )
    years = _non_negative(
        _required_input(inputs, "years_of_service"),
        field_name="years_of_service",
        error_type=SettlementInputError,
    )
    seniority_base = _non_negative(
        _required_input(inputs, "seniority_base_salary"),
        field_name="seniority_base_salary",
        error_type=SettlementInputError,
    )

    preaviso_months = _required_parameter(
        parameters,
        "preaviso_months",
        allow_zero=True,
    )
    integration_days_base = _required_parameter(
        parameters,
        "month_integration_days_base",
        allow_zero=False,
    )
    vacation_days_base = _required_parameter(
        parameters,
        "vacation_days_base",
        allow_zero=False,
    )
    vacation_plus_rate = _required_parameter(
        parameters,
        "vacation_plus_rate",
        allow_zero=True,
    )
    seniority_months_per_year = _required_parameter(
        parameters,
        "seniority_months_per_year",
        allow_zero=True,
    )

    sac_days_worked = inputs.get("sac_days_worked")
    sac_days_base: Decimal | None = None
    if sac_days_worked is not None:
        sac_days_base = _required_parameter(
            parameters,
            "sac_days_base",
            allow_zero=False,
        )

    preaviso_amount = quantize(monthly_salary * preaviso_months, rounding)
    integration_amount = quantize(
        monthly_salary / integration_days_base * integration_days,
        rounding,
    )
    vacation = calculate_vacations(
        monthly_salary,
        vacation_days,
        days_base=vacation_days_base,
        plus_rate=vacation_plus_rate,
        rounding=rounding,
    )
    sac = calculate_sac(
        inputs.get("sac_remunerations"),
        effective_period,
        months_worked=sac_months,
        best_salary=inputs.get("sac_best_salary"),
        days_worked=sac_days_worked,
        days_base=sac_days_base,
        rounding=rounding,
    )
    seniority_amount = quantize(
        seniority_base * years * seniority_months_per_year,
        rounding,
    )

    items = [
        SettlementItem(
            code="PREAVISO",
            name="Preaviso",
            nature=ConceptNature.REMUNERATIVE,
            amount=preaviso_amount,
            quantity=preaviso_months,
            unit="months",
            trace=[
                f"formula=monthly_salary*preaviso_months="
                f"{_format(monthly_salary)}*{_format(preaviso_months)}",
                f"amount={_format(preaviso_amount)}",
            ],
        ),
        SettlementItem(
            code="INTEGRACION_MES",
            name="Integracion del mes",
            nature=ConceptNature.REMUNERATIVE,
            amount=integration_amount,
            quantity=integration_days,
            unit="days",
            trace=[
                f"formula=monthly_salary/month_integration_days_base*integration_days="
                f"{_format(monthly_salary)}/{_format(integration_days_base)}*"
                f"{_format(integration_days)}",
                f"amount={_format(integration_amount)}",
            ],
        ),
        SettlementItem(
            code="VACACIONES_NO_GOZADAS",
            name="Vacaciones no gozadas",
            nature=ConceptNature.REMUNERATIVE,
            amount=vacation.amount,
            quantity=vacation.days,
            unit="days",
            trace=list(vacation.trace),
        ),
        SettlementItem(
            code="SAC_PROPORCIONAL",
            name="SAC proporcional",
            nature=ConceptNature.REMUNERATIVE,
            amount=sac.amount,
            quantity=sac.effective_months,
            unit="months",
            trace=list(sac.trace),
        ),
        SettlementItem(
            code="INDEMNIZACION_ANTIGUEDAD",
            name="Indemnizacion por antiguedad",
            nature=ConceptNature.NON_REMUNERATIVE,
            amount=seniority_amount,
            quantity=years,
            unit="years",
            trace=[
                f"formula=seniority_base_salary*years_of_service*"
                f"seniority_months_per_year={_format(seniority_base)}*"
                f"{_format(years)}*{_format(seniority_months_per_year)}",
                f"amount={_format(seniority_amount)}",
            ],
        ),
    ]

    total = quantize(sum((item.amount for item in items), ZERO), rounding)
    remunerative_total = quantize(
        sum(
            (item.amount for item in items if item.nature == ConceptNature.REMUNERATIVE),
            ZERO,
        ),
        rounding,
    )
    non_remunerative_total = quantize(
        sum(
            (item.amount for item in items if item.nature == ConceptNature.NON_REMUNERATIVE),
            ZERO,
        ),
        rounding,
    )

    trace = [
        f"final settlement period={effective_period.isoformat()}",
        "components: PREAVISO, INTEGRACION_MES, VACACIONES_NO_GOZADAS, "
        "SAC_PROPORCIONAL, INDEMNIZACION_ANTIGUEDAD",
    ]
    for item in items:
        trace.append(f"{item.code}={_format(item.amount)} ({item.nature.value})")
        trace.extend(f"{item.code}: {line}" for line in item.trace)
    trace.extend(
        [
            f"total={_format(total)}",
            f"remunerative_total={_format(remunerative_total)}",
            f"non_remunerative_total={_format(non_remunerative_total)}",
        ]
    )

    return FinalSettlementResult(
        period=effective_period,
        items=items,
        total=total,
        remunerative_total=remunerative_total,
        non_remunerative_total=non_remunerative_total,
        trace=trace,
    )


__all__ = [
    "FinalSettlementResult",
    "SETTLEMENT_ROUNDING",
    "SacResult",
    "SettlementError",
    "SettlementInputError",
    "SettlementItem",
    "SettlementParameterError",
    "VacationResult",
    "calculate_final_settlement",
    "calculate_sac",
    "calculate_vacations",
]
