"""Payroll calculator: evaluate concept definitions and consolidate a payslip.

The calculator is intentionally a thin orchestration layer:

1. normalise employee, novelties and parameters;
2. select definitions valid for the period and the employee's agreement scope,
   and order them with the dependency resolver;
3. evaluate each definition with the DSL engine;
4. classify concept natures and apply the closing identities.

No legal percentages, caps or collective-agreement formulas live here.  Those are
data supplied through formula definitions and parameters.

B-77: what a formula can read. Every name below is exposed under its exact,
upper and lower spellings. All values are exact ``Decimal`` except where noted:

- salary: ``base_salary``/``basic_salary``/``salary``/``salario_basico``/
  ``sueldo``/``basico``/``sueldo_basico``/``sueldo_básico``/``sueldo_basico_mensual``;
- seniority: ``years_of_service``/``service_years``/``years``/``antiguedad``/
  ``antigüedad`` (+ ``_anios`` variants), ``service_months``/``antiguedad_meses``,
  ``service_days``/``antiguedad_dias``;
- workday: ``workday_factor``/``jornada``/``factor_jornada``;
- identity: ``agreement_category``/``categoria``, ``employee_id``/``legajo``,
  ``period_year``/``period_month``/``period_day``;
- every caller parameter and novelty (``<CODE>``/``novedad_<CODE>`` plus
  ``_cantidad``/``_quantity``/``_importe``/``_amount`` suffixes);
- ``start_date``/``period`` are present as ``date`` objects for traceability
  but the DSL only accepts numbers and booleans, so reading them raises a
  ``FormulaError`` by design.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.payroll_engine.concepts import (
    ConceptError,
    NormalizedNovelty,
    aggregate_novelties,
    build_concept_result,
    concept_amounts_by_nature,
    novelty_exposed_names,
    novelty_variables,
    to_decimal,
)
from app.core.payroll_engine.dependency_resolver import (
    DependencyError,
    resolve_dependencies,
)
from app.core.payroll_engine.formula_engine import evaluate_formula
from app.core.payroll_engine.rounding import quantize
from app.core.payroll_engine.types import (
    ConceptNature,
    ConceptResult,
    FormulaContext,
    FormulaDefinition,
    PayrollResult,
    RoundingMode,
    RoundingPolicy,
)

MONEY_ROUNDING = RoundingPolicy(decimals=2, mode=RoundingMode.HALF_UP)


class PayrollCalculationError(ValueError):
    """Raised when a payroll cannot be calculated deterministically."""


class CircularDependencyError(PayrollCalculationError):
    """Raised when formula definitions contain a dependency cycle."""


class UnknownConceptError(PayrollCalculationError):
    """Raised when a formula references a concept that is not defined."""


@dataclass(frozen=True, slots=True)
class EmployeeData:
    """Normalised employee data used by the calculator."""

    id: str
    base_salary: Decimal
    start_date: date
    agreement_category: str | None = None
    workday_factor: Decimal = Decimal("1")
    # B-26: CCT code (e.g. "130/75") used to filter agreement-scoped formulas.
    agreement_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_salary": str(self.base_salary),
            "start_date": self.start_date,
            "agreement_category": self.agreement_category,
            "agreement_code": self.agreement_code,
            "workday_factor": str(self.workday_factor),
        }


def _read(employee: Mapping[str, Any] | object, names: Sequence[str]) -> Any:
    for name in names:
        if isinstance(employee, Mapping):
            if name in employee:
                return employee[name]
        elif hasattr(employee, name):
            return getattr(employee, name)
    return None


def _coerce_date(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise PayrollCalculationError(
                f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}"
            ) from exc
    raise PayrollCalculationError(
        f"{field} must be a date, got {type(value).__name__}"
    )


def _normalise_employee(
    employee: Mapping[str, Any] | object,
    period: date,
) -> EmployeeData:
    raw_id = _read(employee, ("id", "employee_id", "legajo"))
    if raw_id is None or str(raw_id).strip() == "":
        raise PayrollCalculationError("employee is missing required field 'id'")

    raw_salary = _read(employee, ("base_salary", "sueldo_basico", "salary"))
    if raw_salary is None:
        raise PayrollCalculationError(
            f"employee {raw_id!r} is missing required field 'base_salary'"
        )
    try:
        base_salary = to_decimal(raw_salary, field="employee base_salary")
    except ConceptError as exc:
        raise PayrollCalculationError(str(exc)) from exc
    if base_salary is None:  # pragma: no cover - to_decimal only allows None explicitly
        raise PayrollCalculationError("employee base_salary is required")
    if base_salary < 0:
        raise PayrollCalculationError("employee base_salary cannot be negative")

    raw_start = _read(employee, ("start_date", "fecha_ingreso", "hire_date"))
    start_date = period if raw_start is None else _coerce_date(raw_start, field="start_date")

    raw_factor = _read(employee, ("workday_factor", "jornada", "factor_jornada"))
    if raw_factor is None:
        workday_factor = Decimal("1")
    else:
        try:
            factor_value = to_decimal(raw_factor, field="employee workday_factor")
        except ConceptError as exc:
            raise PayrollCalculationError(str(exc)) from exc
        if factor_value is None:  # pragma: no cover - defensive
            raise PayrollCalculationError("employee workday_factor is required")
        if factor_value <= 0:
            raise PayrollCalculationError("employee workday_factor must be greater than zero")
        workday_factor = factor_value

    raw_category = _read(
        employee,
        ("agreement_category", "categoria", "categoría", "category"),
    )
    category = None if raw_category is None else str(raw_category).strip() or None

    raw_agreement = _read(employee, ("agreement_code", "convenio", "cct"))
    agreement = None if raw_agreement is None else str(raw_agreement).strip() or None

    return EmployeeData(
        id=str(raw_id).strip(),
        base_salary=base_salary,
        start_date=start_date,
        agreement_category=category,
        workday_factor=workday_factor,
        agreement_code=agreement,
    )


def _service_time(start_date: date, period: date) -> tuple[Decimal, Decimal, Decimal]:
    """Return completed years, completed months and days of service at ``period``."""

    if start_date > period:
        return Decimal("0"), Decimal("0"), Decimal("0")

    years = period.year - start_date.year
    if (period.month, period.day) < (start_date.month, start_date.day):
        years -= 1
    years = max(years, 0)

    anchor = _add_years(start_date, years)
    months = (period.year - anchor.year) * 12 + (period.month - anchor.month)
    if period.day < anchor.day:
        months -= 1
    months = max(months, 0)
    days = Decimal((period - start_date).days)
    return Decimal(years), Decimal(months), days


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 February -> 28 February in non-leap years
        return value.replace(year=value.year + years, day=28)


def _set_aliases(target: dict[str, Any], name: str, value: Any, *, overwrite: bool = False) -> None:
    for variant in {name, name.upper(), name.lower()}:
        if overwrite or variant not in target:
            target[variant] = value


def _base_variables(employee: EmployeeData, period: date) -> dict[str, Any]:
    years, months, days = _service_time(employee.start_date, period)
    variables: dict[str, Any] = {}

    for name in (
        "base_salary",
        "basic_salary",
        "salary",
        "salario_basico",
        "sueldo",
        "basico",
        "sueldo_basico",
        "sueldo_básico",
        "sueldo_basico_mensual",
    ):
        _set_aliases(variables, name, employee.base_salary)

    for name in (
        "years_of_service",
        "service_years",
        "years",
        "antiguedad",
        "antigüedad",
        "antiguedad_anios",
        "antigüedad_anios",
        "años_antiguedad",
        "años_de_antiguedad",
    ):
        _set_aliases(variables, name, years)
    for name in ("service_months", "antiguedad_meses", "meses_antiguedad"):
        _set_aliases(variables, name, months)
    for name in ("service_days", "antiguedad_dias", "dias_antiguedad"):
        _set_aliases(variables, name, days)

    _set_aliases(variables, "workday_factor", employee.workday_factor)
    _set_aliases(variables, "jornada", employee.workday_factor)
    _set_aliases(variables, "factor_jornada", employee.workday_factor)

    _set_aliases(
        variables,
        "agreement_category",
        employee.agreement_category or "",
    )
    _set_aliases(variables, "categoria", employee.agreement_category or "")
    _set_aliases(variables, "employee_id", employee.id)
    _set_aliases(variables, "legajo", employee.id)

    _set_aliases(variables, "period_year", Decimal(period.year))
    _set_aliases(variables, "period_month", Decimal(period.month))
    _set_aliases(variables, "period_day", Decimal(period.day))

    variables["start_date"] = employee.start_date
    variables["period"] = period
    return variables


def _normalise_parameters(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Convert numeric parameter values to Decimal and keep other values intact."""

    result: dict[str, Any] = {}
    for key, value in (parameters or {}).items():
        name = str(key)
        if isinstance(value, bool) or value is None:
            result[name] = value
            continue
        try:
            converted = to_decimal(value, field=f"parameter {name!r}")
        except ConceptError:
            # Non-numeric parameters can still be used by conditions (e.g. category).
            result[name] = value
        else:
            result[name] = converted
    return result


def _definition_applies(
    definition: FormulaDefinition,
    *,
    agreement_code: str | None,
    category: str | None,
) -> str | None:
    """Return the skip reason when a scoped formula does not match, else ``None``.

    B-26: unscoped definitions apply to every employee. Scoped ones match
    case-insensitively; an employee with unknown scope never matches a scoped
    formula (fail-closed: a CCT-specific rule must not leak to another CCT).
    """

    want_agreement = (definition.agreement_code or "").strip()
    if want_agreement:
        if (agreement_code or "").strip().casefold() != want_agreement.casefold():
            return f"agreement scope {want_agreement!r} does not match employee"
    want_category = (definition.category_code or "").strip()
    if want_category:
        if (category or "").strip().casefold() != want_category.casefold():
            return f"category scope {want_category!r} does not match employee"
    return None


def _select_definitions(
    definitions: Iterable[FormulaDefinition],
    period: date,
    trace: list[str],
    *,
    agreement_code: str | None = None,
    category: str | None = None,
) -> list[FormulaDefinition]:
    selected: list[FormulaDefinition] = []
    by_code: dict[str, FormulaDefinition] = {}

    for definition in definitions:
        if not isinstance(definition, FormulaDefinition):
            raise PayrollCalculationError(
                "definitions must contain FormulaDefinition instances, "
                f"got {type(definition).__name__}"
            )
        if definition.valid_from is not None and period < definition.valid_from:
            trace.append(f"skipped {definition.code}: not valid from {definition.valid_from}")
            continue
        if definition.valid_to is not None and period > definition.valid_to:
            trace.append(f"skipped {definition.code}: not valid until {definition.valid_to}")
            continue
        scope_miss = _definition_applies(
            definition, agreement_code=agreement_code, category=category
        )
        if scope_miss is not None:
            trace.append(f"skipped {definition.code}: {scope_miss}")
            continue
        if definition.code in by_code:
            raise PayrollCalculationError(
                f"duplicate formula definition for code {definition.code!r} in period "
                f"{period.isoformat()}"
            )
        by_code[definition.code] = definition
        selected.append(definition)
    return selected


def _ordered_definitions(
    definitions: list[FormulaDefinition],
) -> list[FormulaDefinition]:
    if not definitions:
        return []

    by_code = {definition.code: definition for definition in definitions}
    try:
        ordered_codes = resolve_dependencies(list(definitions))
    except DependencyError as exc:
        message = str(exc)
        if "circular" in message.lower() or "cycle" in message.lower():
            raise CircularDependencyError(message) from exc
        raise PayrollCalculationError(f"cannot resolve formula dependencies: {message}") from exc
    except Exception as exc:  # defensive: the resolver must never abort silently
        raise PayrollCalculationError(f"cannot resolve formula dependencies: {exc}") from exc

    if not isinstance(ordered_codes, (list, tuple)):
        raise PayrollCalculationError(
            "dependency resolver must return a list of formula codes"
        )

    ordered: list[FormulaDefinition] = []
    seen: set[str] = set()
    for entry in ordered_codes:
        code = entry.code if isinstance(entry, FormulaDefinition) else str(entry)
        definition = by_code.get(code)
        if definition is None:
            raise UnknownConceptError(
                f"dependency resolver returned unknown formula code {code!r}"
            )
        if code in seen:
            continue
        seen.add(code)
        ordered.append(definition)

    missing = [code for code in by_code if code not in seen]
    if missing:
        raise CircularDependencyError(
            "could not order all formulas; circular dependency or missing reference "
            f"among: {', '.join(sorted(missing))}"
        )
    return ordered


def _referenced_variable_names(
    definitions: Sequence[FormulaDefinition],
) -> set[str]:
    """Collect every variable/condition-field name the definitions can read."""
    names: set[str] = set()

    # Iterative (B-33): name scanning must not exhaust the call stack on
    # deeply nested trees; depth itself is rejected by validation/evaluation.
    stack: list[Any] = []
    for definition in definitions:
        stack.append(definition.formula)
        stack.extend(definition.conditions)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if set(node) == {"variable"} and isinstance(node["variable"], str):
                names.add(node["variable"])
            field = node.get("field")
            if isinstance(field, str) and set(node) <= {"field", "operator", "value"}:
                names.add(field)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return names


def _concept_context(
    *,
    variables: Mapping[str, Any],
    parameters: Mapping[str, Any],
    concepts: Mapping[str, Any],
    period: date,
    definition: FormulaDefinition,
    employee: EmployeeData,
    definitions: Sequence[FormulaDefinition],
    novelties: Mapping[str, NormalizedNovelty],
    items: Sequence[ConceptResult],
) -> FormulaContext:
    return FormulaContext(
        variables=variables,
        parameters=parameters,
        concepts=concepts,
        functions={},
        period=period,
        extra={
            "definition": definition,
            "employee": employee.to_dict(),
            "definitions": definitions,
            "novelties": novelties,
            "items": tuple(items),
        },
    )


def calculate_payroll(
    employee: Mapping[str, Any] | object,
    period: date,
    definitions: Sequence[FormulaDefinition],
    parameters: Mapping[str, Any] | None = None,
    novelties: Iterable[Mapping[str, Any] | object] | None = None,
) -> PayrollResult:
    """Calculate one employee's payslip for a period.

    Parameters
    ----------
    employee:
        Mapping or dataclass with ``id``, ``base_salary``, ``start_date``,
        ``agreement_category`` and ``workday_factor``.  Spanish aliases such as
        ``legajo``/``sueldo_basico``/``fecha_ingreso`` are also accepted.
    period:
        Payroll period date.  Formula validity and seniority are evaluated against it.
    definitions:
        Formula definitions to execute.  Definitions outside their validity range are
        skipped.  Dependencies are resolved with the DSL dependency resolver.
    parameters:
        Period parameters referenced by formulas.  Numeric values are normalised to
        ``Decimal``; missing limits/parameters are simply absent.
    novelties:
        Novelties with ``code``, ``quantity``, ``amount``, ``unit`` and ``kind``.
        Same-code novelties are aggregated, matching the domain rule that novelties
        of the same type add up inside the period.

    Raises
    ------
    PayrollCalculationError
        For invalid inputs or a formula that cannot be evaluated.
    CircularDependencyError
        When the definitions contain a dependency cycle.
    """

    if isinstance(period, datetime):
        period = period.date()
    if not isinstance(period, date):
        raise PayrollCalculationError(
            f"period must be a date, got {type(period).__name__}"
        )

    data = _normalise_employee(employee, period)
    trace: list[str] = [
        f"employee={data.id} period={period.isoformat()}",
        f"workday_factor={data.workday_factor}",
    ]

    selected = _select_definitions(
        definitions,
        period,
        trace,
        agreement_code=data.agreement_code,
        category=data.agreement_category,
    )
    ordered = _ordered_definitions(selected)
    trace.append("calculation order: " + ", ".join(item.code for item in ordered))

    params = _normalise_parameters(parameters)
    aggregated_novelties = aggregate_novelties(novelties)

    variables: dict[str, Any] = _base_variables(data, period)
    # B-31: a parameter colliding with a base variable does not override it
    # (the base value wins below for ``{"variable"}``/``{"field"}`` reads;
    # only explicit ``{"parameter"}`` nodes see the parameter value).
    # It is reported instead of silently ignored.
    base_names = {name.casefold() for name in variables}
    shadowed_parameters = [name for name in params if name.casefold() in base_names]
    # Parameters are also exposed as variables so conditions written with the
    # ``{"field": ...}`` shorthand (see plan.md section 6.2) can reference them.
    # Explicit ``{"parameter": ...}`` nodes keep working through FormulaContext.
    for name, value in params.items():
        _set_aliases(variables, name, value)
    # B-11: novelties readable through no definition are listed instead of
    # silently ignored. Names shadowed by base/parameter variables are dead
    # (setdefault below keeps the base value), so they do not count as reads.
    referenced = {name.casefold() for name in _referenced_variable_names(ordered)}
    shadowed = {name.casefold() for name in variables}
    readable = referenced - shadowed
    unconsumed_novelties = [
        novelty.code
        for novelty in aggregated_novelties.values()
        if not {
            name.casefold() for name in novelty_exposed_names(novelty)
        } & readable
    ]
    for name, value in novelty_variables(novelties).items():
        variables.setdefault(name, value)

    concepts: dict[str, Any] = {}
    items: list[ConceptResult] = []

    for definition in ordered:
        context = _concept_context(
            variables=variables,
            parameters=params,
            concepts=concepts,
            period=period,
            definition=definition,
            employee=data,
            definitions=ordered,
            novelties=aggregated_novelties,
            items=items,
        )
        try:
            formula_result = evaluate_formula(definition, context)
        except Exception as exc:
            raise PayrollCalculationError(
                f"error calculating concept {definition.code!r}: {exc}"
            ) from exc

        # evaluate_formula already applies definition.rounding; quantizing again is
        # idempotent and keeps the calculator correct if a definition is evaluated by
        # another implementation.
        amount = quantize(formula_result.value, definition.rounding)
        item = build_concept_result(definition, formula_result, amount=amount)
        items.append(item)

        concepts[definition.code] = amount
        for alias in (definition.code.upper(), definition.code.lower()):
            concepts.setdefault(alias, amount)
        for alias in (
            f"concept_{definition.code}",
            f"concept_{definition.code.upper()}",
            f"concepto_{definition.code}",
        ):
            variables.setdefault(alias, amount)

        trace.append(
            f"{definition.code}={amount} ({definition.nature.value})"
        )
        trace.extend(f"{definition.code}: {line}" for line in item.trace)

    remunerative = quantize(
        concept_amounts_by_nature(items, ConceptNature.REMUNERATIVE),
        MONEY_ROUNDING,
    )
    non_remunerative = quantize(
        concept_amounts_by_nature(items, ConceptNature.NON_REMUNERATIVE),
        MONEY_ROUNDING,
    )
    deductions = quantize(
        concept_amounts_by_nature(items, ConceptNature.DEDUCTION),
        MONEY_ROUNDING,
    )
    contributions = quantize(
        concept_amounts_by_nature(items, ConceptNature.CONTRIBUTION),
        MONEY_ROUNDING,
    )

    gross = quantize(remunerative + non_remunerative, MONEY_ROUNDING)
    net = quantize(gross - deductions, MONEY_ROUNDING)
    employer_cost = quantize(gross + contributions, MONEY_ROUNDING)

    trace.extend(
        [
            f"remunerative={remunerative}",
            f"non_remunerative={non_remunerative}",
            f"deductions={deductions}",
            f"contributions={contributions}",
            f"gross={gross}",
            f"net={net}",
            f"employer_cost={employer_cost}",
        ]
    )
    trace.extend(f"unconsumed novelty: {code}" for code in unconsumed_novelties)
    trace.extend(
        f"shadowed parameter: {name!r} collides with a base variable (base value wins)"
        for name in shadowed_parameters
    )

    return PayrollResult(
        employee_id=data.id,
        period=period,
        items=items,
        remunerative=remunerative,
        non_remunerative=non_remunerative,
        deductions=deductions,
        contributions=contributions,
        gross=gross,
        net=net,
        employer_cost=employer_cost,
        trace=trace,
        unconsumed_novelties=unconsumed_novelties,
        shadowed_parameters=shadowed_parameters,
    )


__all__ = [
    "CircularDependencyError",
    "EmployeeData",
    "MONEY_ROUNDING",
    "PayrollCalculationError",
    "UnknownConceptError",
    "calculate_payroll",
]
