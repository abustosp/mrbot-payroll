"""Persist deterministic payroll calculations for one payroll run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.payroll_engine.calculator import _definition_applies, calculate_payroll
from app.core.payroll_engine.settlements import (
    calculate_final_settlement,
    calculate_sac,
    calculate_vacations,
)
from app.core.payroll_engine.types import (
    ConceptNature,
    FormulaStatus,
    RoundingMode,
    RoundingPolicy,
)
from app.core.payroll_engine.types import (
    FormulaDefinition as FormulaContract,
)
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Employee,
    EmploymentContract,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
    PayrollItem,
    PayrollNovelty,
    PayrollResult,
    PayrollRun,
    PayrollTrace,
    Ruleset,
    SalaryScale,
)


class PayrollRunStateError(ValueError):
    """The run is in a state that cannot be recalculated."""


#: Run types calculated by the settlement engine instead of monthly formulas.
SETTLEMENT_RUN_TYPES = ("SAC", "VACATIONS", "FINAL")

#: Settlement inputs ride on AUXILIARY novelties of the run period so no new
#: input table is needed. Missing inputs are employee errors (fail-closed);
#: unknown codes still fall under the V2-09 unconsumed-novelty rule.
VAC_DAYS_CODE = "VAC_DIAS"
VAC_PLUS_RATE_CODE = "VAC_PLUS_TASA"
FINAL_INTEGRATION_DAYS_CODE = "LIQ_DIAS_INTEGRACION"

#: Required ``NormativeParameter`` codes (jurisdiction ``AR``) for FINAL runs.
#: There are no legal defaults: a missing row is an employee error. Each DB
#: code maps to the engine parameter name expected by
#: :func:`calculate_final_settlement`.
FINAL_PARAMETER_CODES: dict[str, str] = {
    "liq_preaviso_meses": "preaviso_months",
    "liq_integracion_dias_base": "month_integration_days_base",
    "liq_vacaciones_dias_base": "vacation_days_base",
    "liq_vacaciones_plus_tasa": "vacation_plus_rate",
    "liq_antiguedad_meses_por_anio": "seniority_months_per_year",
}

#: PayrollConcept codes every settlement run type persists. The organization
#: must create them (same house rule as monthly formulas without concept).
SETTLEMENT_CONCEPT_CODES: dict[str, tuple[str, ...]] = {
    "SAC": ("SAC",),
    "VACATIONS": ("VACACIONES",),
    "FINAL": (
        "PREAVISO",
        "INTEGRACION_MES",
        "VACACIONES_NO_GOZADAS",
        "SAC_PROPORCIONAL",
        "INDEMNIZACION_ANTIGUEDAD",
    ),
}

#: Novelty codes each settlement run type consumes (V2-09 applies to the rest).
SETTLEMENT_CONSUMED_CODES: dict[str, frozenset[str]] = {
    "SAC": frozenset(),
    "VACATIONS": frozenset({VAC_DAYS_CODE, VAC_PLUS_RATE_CODE}),
    "FINAL": frozenset({VAC_DAYS_CODE, FINAL_INTEGRATION_DAYS_CODE}),
}

#: Run statuses whose persisted results count as semester history for SAC.
_SAC_HISTORY_STATUSES = ("CALCULATED", "IN_REVIEW", "APPROVED", "CLOSED")


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _applicable_formulas(
    db: Session, organization_id: int, period: date
) -> list[tuple[FormulaDefinition, FormulaVersion]]:
    rows = db.execute(
        select(FormulaDefinition, FormulaVersion)
        .join(FormulaVersion, FormulaVersion.formula_id == FormulaDefinition.id)
        .where(
            FormulaDefinition.organization_id == organization_id,
            FormulaVersion.status == "APPROVED",
            FormulaVersion.valid_from <= period,
            or_(FormulaVersion.valid_to.is_(None), FormulaVersion.valid_to >= period),
        )
        .order_by(FormulaDefinition.code, FormulaVersion.version.desc())
    ).all()
    latest: dict[int, tuple[FormulaDefinition, FormulaVersion]] = {}
    for formula, version in rows:
        latest.setdefault(formula.id, (formula, version))
    return sorted(latest.values(), key=lambda row: row[0].code)


def _applicable_parameters(db: Session, period: date) -> dict[str, Decimal]:
    rows = db.scalars(
        select(NormativeParameter)
        .where(
            NormativeParameter.jurisdiction == "AR",
            NormativeParameter.valid_from <= period,
            or_(NormativeParameter.valid_to.is_(None), NormativeParameter.valid_to >= period),
        )
        .order_by(
            NormativeParameter.code,
            NormativeParameter.version.desc(),
            NormativeParameter.valid_from.desc(),
        )
    ).all()
    parameters: dict[str, Decimal] = {}
    for row in rows:
        parameters.setdefault(row.code, row.value)
    return parameters


def _novelties_for_employees(
    db: Session,
    organization_id: int,
    employee_ids: list[int],
    period: date,
) -> dict[int, list[dict[str, object]]]:
    """Load period novelties using the contract expected by ``calculate_payroll``.

    Only the persisted values are mapped; aggregation and business rules stay in
    the payroll engine.

    Contract note: ``calculate_payroll`` raises when a formula references a
    novelty variable that is absent. Consequently, a formula that consumes
    novelties needs a row for every employee it is evaluated for; the service
    does not invent zero-valued novelties to hide missing inputs.
    """
    if not employee_ids:
        return {}
    period_key = f"{period.year:04d}{period.month:02d}"
    rows = db.scalars(
        select(PayrollNovelty)
        .where(
            PayrollNovelty.organization_id == organization_id,
            PayrollNovelty.employee_id.in_(employee_ids),
            PayrollNovelty.period == period_key,
        )
        .order_by(PayrollNovelty.id)
    ).all()
    novelties: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        novelties.setdefault(row.employee_id, []).append(
            {
                "code": row.code,
                "quantity": row.quantity,
                "amount": row.amount,
                "unit": row.unit,
                "kind": row.kind,
            }
        )
    return novelties


def _load_catalog_coverage() -> dict[str, dict[str, str | None]]:
    """Best-effort CCT coverage from the catalog file; ``{}`` when unavailable."""
    try:
        from pathlib import Path

        from app.config import get_settings
        from app.core.normative.package_loader import cct_coverage_map

        path = Path(get_settings().normative_cct_dir) / "catalog.json"
        if not path.is_file():
            return {}
        with path.open(encoding="utf-8") as handle:
            return cct_coverage_map(json.load(handle))
    except Exception:
        return {}


_COVERAGE_OK_STATUSES = frozenset(
    {"current", "verified", "verificado", "approved", "aprobado", "vigente"}
)


def _cct_coverage_warnings(
    codes: list[str],
    coverage: dict[str, dict[str, str | None]],
    period: date,
) -> list[dict[str, str | int]]:
    """Warn (never block) when a CCT is outside its catalog coverage."""
    findings: list[dict[str, str | int]] = []
    for code in sorted(set(codes)):
        entry = coverage.get(code)
        if not entry:
            continue
        vigencia = entry.get("vigencia_hasta")
        if vigencia:
            try:
                covered_until = date.fromisoformat(vigencia)
            except ValueError:
                covered_until = None
            if covered_until is not None and period > covered_until:
                findings.append({
                    "type": "cct_coverage",
                    "code": code,
                    "message": (
                        f"El CCT {code} quedó fuera de cobertura en "
                        f"{vigencia}; el período {period.isoformat()} "
                        "liquida sin escala vigente verificada."
                    ),
                })
        status = (entry.get("status") or "").strip().casefold()
        if status and status not in _COVERAGE_OK_STATUSES:
            findings.append({
                "type": "cct_coverage",
                "code": code,
                "message": (
                    f"El CCT {code} figura con estado {status}; "
                    "la cobertura del catálogo no está vigente."
                ),
            })
    return findings


def _clear_previous_results(db: Session, run_id: int) -> None:
    result_ids = select(PayrollResult.id).where(PayrollResult.payroll_run_id == run_id)
    db.execute(delete(PayrollItem).where(PayrollItem.payroll_result_id.in_(result_ids)))
    db.execute(delete(PayrollTrace).where(PayrollTrace.payroll_run_id == run_id))
    db.execute(delete(PayrollResult).where(PayrollResult.payroll_run_id == run_id))


def _definitions_for_employee(
    formulas: list[tuple[FormulaDefinition, FormulaVersion]],
    concepts: dict[str, PayrollConcept],
) -> list[FormulaContract]:
    definitions: list[FormulaContract] = []
    for formula, version in formulas:
        concept = concepts.get(formula.code)
        if concept is None:
            raise ValueError(f"No hay un concepto configurado para {formula.code}.")
        # B-07: the service executes conditions/rounding/depends_on exactly as
        # approved; anything else would silently overpay (older rows carry
        # NULL and keep the historical default policy).
        rounding = RoundingPolicy()
        if version.rounding:
            rounding = RoundingPolicy.model_validate(version.rounding)
        definitions.append(
            FormulaContract(
                code=formula.code,
                description=formula.description or concept.name,
                formula=version.expression,
                conditions=list(version.conditions or []),
                depends_on=list(version.depends_on or []),
                rounding=rounding,
                nature=ConceptNature(concept.nature),
                valid_from=version.valid_from,
                valid_to=version.valid_to,
                status=FormulaStatus(version.status),
                version=version.version,
                source=f"formula_version:{version.id}",
                # B-26: agreement scope travels with the definition so the
                # calculator filters per employee before evaluating.
                agreement_code=formula.agreement_code,
                category_code=formula.category_code,
            )
        )
    if not definitions:
        raise ValueError("No hay fórmulas aprobadas vigentes para el período.")
    return definitions


def _snapshot_ruleset(
    db: Session,
    run: PayrollRun,
    formulas: list[tuple[FormulaDefinition, FormulaVersion]],
    parameters: dict[str, Decimal],
    inputs_hash: str,
    period: date,
) -> Ruleset:
    """Persist an immutable snapshot of the normative package applied (B-27).

    A new ``Ruleset`` row is inserted on every calculation; rows are never
    updated, so reliquidating an old period with rewritten rules cannot
    silently change history — the run keeps pointing at its sealed package.
    """

    snapshot = {
        "run_id": run.id,
        "period": period.isoformat(),
        "inputs_hash": inputs_hash,
        "formulas": [
            {
                "formula_id": formula.id,
                "code": formula.code,
                "version_id": version.id,
                "version": version.version,
                "expression": version.expression,
                "conditions": version.conditions,
                "depends_on": version.depends_on,
                "rounding": version.rounding,
                "agreement_code": formula.agreement_code,
                "category_code": formula.category_code,
                "valid_from": version.valid_from.isoformat(),
                "valid_to": version.valid_to.isoformat() if version.valid_to else None,
                "status": version.status,
            }
            for formula, version in formulas
        ],
        "parameters": {code: str(value) for code, value in parameters.items()},
    }
    # Shared code with a global version sequence (run codes can fill the
    # 80-char column; the run links back through run.ruleset_id).
    code = "payroll-run"
    latest = db.scalar(select(func.max(Ruleset.version)).where(Ruleset.code == code))
    ruleset = Ruleset(
        code=code,
        version=(latest or 0) + 1,
        status="APPROVED",
        rules=snapshot,
    )
    db.add(ruleset)
    db.flush()
    return ruleset


def calculate_payroll_run(
    db: Session,
    run: PayrollRun,
    *,
    include_items: bool = True,
    results_limit: int | None = None,
    results_offset: int = 0,
    allow_unconsumed_novelties: bool = False,
) -> dict:
    """Calculate eligible employees and replace all results already stored for ``run``.

    The VALIDATING state is committed before calculating, so callers must not
    hold an explicit transaction across this call. Final results are flushed;
    the caller commits them (or rolls back on error).

    B-36: ``include_items``/``results_limit``/``results_offset`` paginate the
    per-employee detail in the response. The summary (totals over every
    calculated employee) is always complete; every result row is still
    persisted regardless of the window.

    V2-09: a novelty no formula consumes leaves the run in ERROR unless
    ``allow_unconsumed_novelties`` is set (explicit opt-out to ignore it).
    """
    if run.status not in {"DRAFT", "CALCULATED", "IN_REVIEW", "ERROR"}:
        raise PayrollRunStateError(
            "No se puede calcular una liquidación aprobada o cerrada "
            "(tampoco una ya en cálculo)."
        )
    if run.run_type not in ("MONTHLY", *SETTLEMENT_RUN_TYPES):
        # B-10: un run_type desconocido no se liquida como mensual en
        # silencio (la API ya rechaza valores fuera de SUPPORTED_RUN_TYPES).
        raise PayrollRunStateError(
            f"run_type {run.run_type!r} no soportado; "
            f"tipos soportados: MONTHLY, {', '.join(SETTLEMENT_RUN_TYPES)}."
        )

    # B-13: reclamo atómico del estado con commit antes de calcular. El
    # UPDATE condicional solo avanza desde estados calculables; si otro
    # request ya tomó la corrida (0 filas), se devuelve 409 en vez de
    # pisarse (borrar/insertar entrelazados). En Postgres el UPDATE
    # concurrente se serializa por fila; ver D-2 para FOR UPDATE.
    claimed = db.execute(
        update(PayrollRun)
        .where(
            PayrollRun.id == run.id,
            PayrollRun.status.in_(("DRAFT", "CALCULATED", "IN_REVIEW", "ERROR")),
        )
        .values(status="VALIDATING")
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount == 0:
        db.rollback()
        raise PayrollRunStateError(
            "La liquidación ya está en cálculo o no está en un estado "
            "calculable (aprobada o cerrada)."
        )
    run.status = "VALIDATING"
    db.commit()
    try:
        if run.run_type in SETTLEMENT_RUN_TYPES:
            return _run_settlement(
                db,
                run,
                include_items=include_items,
                results_limit=results_limit,
                results_offset=results_offset,
                allow_unconsumed_novelties=allow_unconsumed_novelties,
            )
        return _run_calculation(
            db,
            run,
            include_items=include_items,
            results_limit=results_limit,
            results_offset=results_offset,
            allow_unconsumed_novelties=allow_unconsumed_novelties,
        )
    except Exception:
        # Un cálculo fallido queda reintentable en vez de atascado en VALIDATING.
        db.rollback()
        run.status = "ERROR"
        db.add(run)
        db.commit()
        raise


def _load_active_population(
    db: Session, run: PayrollRun, period: date
) -> tuple[list[Employee], list[Employee], dict[int, list[EmploymentContract]]]:
    """Employees eligible for a monthly-like run with their valid contracts.

    Returns ``(employees, omitted, contracts_by_employee)``. The omitted
    channel (B-17) lists actives without a valid contract so an incomplete
    payroll never looks complete.
    """

    employees = db.scalars(
        select(Employee)
        .join(EmploymentContract, EmploymentContract.employee_id == Employee.id)
        .where(
            Employee.organization_id == run.organization_id,
            Employee.active.is_(True),
            or_(
                Employee.termination_date.is_(None),
                Employee.termination_date >= period,
            ),
            EmploymentContract.company_id == run.company_id,
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= period,
            or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= period),
        )
        .order_by(Employee.id)
    ).unique().all()
    employees = list(employees)
    included_ids = {employee.id for employee in employees}
    omitted = [
        candidate
        for candidate in db.scalars(
            select(Employee)
            .where(
                Employee.organization_id == run.organization_id,
                Employee.active.is_(True),
                or_(
                    Employee.termination_date.is_(None),
                    Employee.termination_date >= period,
                ),
            )
            .order_by(Employee.id)
        ).all()
        if candidate.id not in included_ids
    ]
    contracts = db.scalars(
        select(EmploymentContract).where(
            EmploymentContract.company_id == run.company_id,
            EmploymentContract.employee_id.in_(sorted(included_ids)),
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= period,
            or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= period),
        )
    ).all() if included_ids else []
    contracts_by_employee: dict[int, list[EmploymentContract]] = {}
    for contract_row in contracts:
        contracts_by_employee.setdefault(contract_row.employee_id, []).append(contract_row)
    return employees, omitted, contracts_by_employee


def _preload_agreement_data(
    db: Session,
    contracts_by_employee: dict[int, list[EmploymentContract]],
    period: date,
) -> tuple[
    dict[int, AgreementCategory],
    dict[int, list[SalaryScale]],
    set[int],
    dict[int, str],
]:
    """Preload categories, scales and agreement codes with one query each (B-35)."""

    category_ids = {
        contract_row.category_id
        for contract_list in contracts_by_employee.values()
        for contract_row in contract_list
        if contract_row.category_id is not None
    }
    categories = (
        {
            category.id: category
            for category in db.scalars(
                select(AgreementCategory).where(AgreementCategory.id.in_(category_ids))
            ).all()
        }
        if category_ids
        else {}
    )
    scales_by_category: dict[int, list[SalaryScale]] = {}
    if category_ids:
        for scale_row in db.scalars(
            select(SalaryScale).where(
                SalaryScale.category_id.in_(category_ids),
                SalaryScale.valid_from <= period,
                or_(SalaryScale.valid_to.is_(None), SalaryScale.valid_to >= period),
            )
        ).all():
            scales_by_category.setdefault(scale_row.category_id, []).append(scale_row)
        for group in scales_by_category.values():
            group.sort(key=lambda item: item.valid_from, reverse=True)
    agreement_ids = {
        contract_row.agreement_id
        for contract_list in contracts_by_employee.values()
        for contract_row in contract_list
        if contract_row.agreement_id is not None
    }
    agreement_codes = (
        dict(
            db.execute(
                select(CollectiveAgreement.id, CollectiveAgreement.code).where(
                    CollectiveAgreement.id.in_(sorted(agreement_ids))
                )
            ).all()
        )
        if agreement_ids
        else {}
    )
    return categories, scales_by_category, agreement_ids, agreement_codes


def _resolve_base_salary(
    contract: EmploymentContract,
    scales_by_category: dict[int, list[SalaryScale]],
) -> Decimal | None:
    """Monthly base salary: contract amount, else the single valid scale."""

    scale = None
    if contract.category_id is not None:
        candidate_scales = scales_by_category.get(contract.category_id, [])
        if len(candidate_scales) == 1:
            scale = candidate_scales[0]
    if contract.monthly_salary is not None:
        return contract.monthly_salary
    if scale is not None:
        return scale.base_salary + scale.additional
    return None


def _run_calculation(
    db: Session,
    run: PayrollRun,
    *,
    include_items: bool = True,
    results_limit: int | None = None,
    results_offset: int = 0,
    allow_unconsumed_novelties: bool = False,
) -> dict:
    """Heavy body of :func:`calculate_payroll_run` (run is already VALIDATING)."""

    period = run.period_end
    _clear_previous_results(db, run.id)
    formulas = _applicable_formulas(db, run.organization_id, period)
    parameters = _applicable_parameters(db, period)
    concept_rows = db.scalars(
        select(PayrollConcept).where(
            PayrollConcept.organization_id == run.organization_id,
            PayrollConcept.active.is_(True),
        )
    ).all()
    concepts = {concept.code: concept for concept in concept_rows}
    # B-35: definitions are identical for every employee, so they are built
    # once (B-26 scope filtering per employee below is a cheap list filter).
    # A missing concept or an empty formula set keeps the historical
    # per-employee error channel instead of aborting the whole run.
    base_definitions: list[FormulaContract] | None
    definitions_error = ""
    try:
        base_definitions = _definitions_for_employee(formulas, concepts)
    except ValueError as exc:
        base_definitions = None
        definitions_error = str(exc)

    # B-79: payslip formulas use decimals=2 HALF_UP; anything else (notably
    # decimals=0, off by up to $0.50 per concept) is warned, never coerced.
    rounding_warnings: list[dict[str, str | int]] = []
    if base_definitions is not None:
        for scoped in base_definitions:
            if (
                scoped.rounding.decimals != 2
                or scoped.rounding.mode != RoundingMode.HALF_UP
            ):
                rounding_warnings.append({
                    "type": "rounding_policy",
                    "code": scoped.code,
                    "message": (
                        f"La fórmula {scoped.code} redondea con "
                        f"decimals={scoped.rounding.decimals} "
                        f"mode={scoped.rounding.mode}; los recibos usan "
                        "decimals=2 HALF_UP (floor/ceil solo si la norma lo exige)."
                    ),
                })

    employees, omitted, contracts_by_employee = _load_active_population(
        db, run, period
    )
    employee_ids = [employee.id for employee in employees]
    novelties_by_employee = _novelties_for_employees(
        db, run.organization_id, employee_ids, period
    )
    categories, scales_by_category, agreement_ids, agreement_codes = (
        _preload_agreement_data(db, contracts_by_employee, period)
    )

    results: list[dict] = []
    errors: list[dict[str, str | int]] = []
    warnings: list[dict[str, str | int]] = list(rounding_warnings)
    run_agreement_codes: set[str] = set()
    input_employees: list[dict] = []
    # B-36: summary accumulators stay complete when the detail is paginated.
    calculated_total = 0
    gross_total = Decimal("0")
    net_total = Decimal("0")
    result_hashes: list[str] = []
    for candidate in omitted:
        errors.append({
            "employee_id": candidate.id,
            "employee_code": candidate.employee_code,
            "message": (
                "El empleado activo no tiene un contrato vigente para la "
                "empresa y el período; quedó fuera de la liquidación."
            ),
        })
        db.add(PayrollTrace(
            payroll_run_id=run.id,
            employee_id=candidate.id,
            event="EMPLOYEE_ERROR",
            detail={"message": (
                "El empleado activo no tiene un contrato vigente para la "
                "empresa y el período; quedó fuera de la liquidación."
            )},
        ))
    for employee in employees:
        employee_contracts = contracts_by_employee.get(employee.id, [])
        if len(employee_contracts) != 1:
            errors.append({
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "message": "Se requiere exactamente un contrato vigente para el período.",
            })
            continue
        contract = employee_contracts[0]

        scale = None
        category = None
        if contract.category_id is not None:
            category = categories.get(contract.category_id)
            candidate_scales = scales_by_category.get(contract.category_id, [])
            if len(candidate_scales) == 1:
                scale = candidate_scales[0]
        agreement_code = agreement_codes.get(contract.agreement_id or -1)
        if agreement_code:
            run_agreement_codes.add(agreement_code)
        base_salary = _resolve_base_salary(contract, scales_by_category)

        employee_novelties = novelties_by_employee.get(employee.id, [])
        # B-02: the scale base and its non-remunerative part travel as
        # distinct variables so formulas can target them separately.
        employee_parameters = dict(parameters)
        if scale is not None:
            employee_parameters.setdefault("escala_basico", scale.base_salary)
            employee_parameters.setdefault("escala_adicional", scale.additional)
        input_employees.append({
            "employee_id": employee.id,
            "contract_id": contract.id,
            "category_id": contract.category_id,
            "scale_id": scale.id if scale else None,
            "category_code": category.code if category else None,
            "base_salary": base_salary,
            "scale_additional": scale.additional if scale else None,
            "scale_amount_type": scale.amount_type if scale else None,
            "hire_date": employee.hire_date,
            "contract_valid_from": contract.valid_from,
            "contract_valid_to": contract.valid_to,
            "novelties": employee_novelties,
            "formula_versions": [
                {"code": formula.code, "version": version.version, "expression": version.expression}
                for formula, version in formulas
            ],
        })
        try:
            if category is None:
                raise ValueError("El contrato no tiene una categoría vigente configurada.")
            if base_salary is None:
                raise ValueError(f"No hay una escala salarial única vigente para {category.code}.")
            if base_definitions is None:
                raise ValueError(definitions_error)
            # B-26: agreement-scoped formulas only run for matching employees.
            definitions = [
                definition
                for definition in base_definitions
                if _definition_applies(
                    definition,
                    agreement_code=agreement_code,
                    category=category.code,
                )
                is None
            ]
            if not definitions:
                raise ValueError(
                    "No hay fórmulas aplicables al convenio/categoría del empleado "
                    "para el período."
                )
            calculated = calculate_payroll(
                {
                    "id": employee.id,
                    "base_salary": base_salary,
                    "start_date": employee.hire_date or contract.valid_from,
                    "agreement_category": category.code,
                    "agreement_code": agreement_code,
                },
                period,
                definitions,
                employee_parameters,
                novelties=employee_novelties,
            )
            if any(len(item.code) > 40 for item in calculated.items):
                raise ValueError("El código de un concepto supera los 40 caracteres permitidos.")
            if calculated.net < 0:
                raise ValueError(
                    "El resultado de la liquidación tiene un neto negativo "
                    f"({calculated.net})."
                )
        except (ArithmeticError, LookupError, TypeError, ValueError) as exc:
            message = str(exc)
            errors.append({
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "message": message,
            })
            db.add(PayrollTrace(
                payroll_run_id=run.id,
                employee_id=employee.id,
                event="EMPLOYEE_ERROR",
                detail={"message": message},
            ))
            continue

        serialized = calculated.to_dict()
        row_hash = _digest(serialized)
        # B-31: parameters shadowed by a base variable are reported too.
        for name in calculated.shadowed_parameters:
            warnings.append({
                "type": "parameter_shadowed",
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "code": name,
                "message": (
                    f"El parámetro {name} colisiona con una variable base "
                    "y no la sobrescribe (vale la base)."
                ),
            })
        result = PayrollResult(
            payroll_run_id=run.id,
            employee_id=employee.id,
            remunerative=calculated.remunerative,
            non_remunerative=calculated.non_remunerative,
            deductions=calculated.deductions,
            contributions=calculated.contributions,
            gross=calculated.gross,
            net=calculated.net,
            employer_cost=calculated.employer_cost,
            calculated_at=datetime.now(UTC),
            results_hash=row_hash,
        )
        db.add(result)
        db.flush()
        for item in calculated.items:
            db.add(PayrollItem(
                payroll_result_id=result.id,
                concept_id=concepts[item.code].id,
                code=item.code,
                description=item.name,
                nature=item.nature.value,
                quantity=item.quantity,
                unit_value=item.unit_value,
                amount=item.amount,
            ))
        db.add(PayrollTrace(
            payroll_result_id=result.id,
            payroll_run_id=run.id,
            employee_id=employee.id,
            event="CALCULATED",
            detail={
                "period": period.isoformat(),
                "formula_versions": [
                    {"code": formula.code, "version": version.version}
                    for formula, version in formulas
                ],
                "lines": calculated.trace,
            },
        ))
        # V2-09: novelties consumed by no formula are errors by default, so
        # unpaid overtime cannot look paid (B-11 keeps the warning channel
        # only under the explicit opt-out flag).
        for code in calculated.unconsumed_novelties:
            entry: dict[str, str | int] = {
                "type": "novelty_not_consumed",
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "code": code,
                "message": (
                    f"La novedad {code} del período no fue consumida "
                    "por ninguna fórmula."
                ),
            }
            if allow_unconsumed_novelties:
                warnings.append(entry)
            else:
                errors.append(entry)
                db.add(PayrollTrace(
                    payroll_run_id=run.id,
                    payroll_result_id=result.id,
                    employee_id=employee.id,
                    event="NOVELTY_NOT_CONSUMED",
                    detail={"message": entry["message"], "code": code},
                ))
        # B-36: every row is persisted, but only the requested window is
        # serialized into the response; totals below always cover everyone.
        slot = calculated_total
        calculated_total += 1
        gross_total += calculated.gross
        net_total += calculated.net
        result_hashes.append(row_hash)
        if (
            include_items
            and slot >= results_offset
            and (results_limit is None or len(results) < results_limit)
        ):
            results.append({
                "id": result.id,
                "employee_id": employee.id,
                "remunerative": str(result.remunerative),
                "non_remunerative": str(result.non_remunerative),
                "deductions": str(result.deductions),
                "contributions": str(result.contributions),
                "gross": str(result.gross),
                "net": str(result.net),
                "employer_cost": str(result.employer_cost),
                "items": [item.to_dict() for item in calculated.items],
                "trace": calculated.trace,
            })

    inputs_hash = _digest({
        "run_id": run.id,
        "company_id": run.company_id,
        "period_start": run.period_start,
        "period_end": run.period_end,
        "run_type": run.run_type,
        "employees": input_employees,
        "formula_versions": [
            {"formula_id": formula.id, "version_id": version.id, "version": version.version}
            for formula, version in formulas
        ],
        "parameters": parameters,
    })
    run.inputs_hash = inputs_hash
    # B-26: la corrida abarca varios CCT y alguna fórmula no tiene scope, así
    # que puede aplicarse donde no corresponde; se avisa sin bloquear y se
    # nombran las fórmulas para que el alcance se asigne en el acto.
    if len(run_agreement_codes) > 1:
        unscoped = sorted({
            formula.code
            for formula, _version in formulas
            if not (formula.agreement_code or "").strip()
        })
        if unscoped:
            warnings.append({
                "type": "multi_cct_no_scope",
                "codes": ", ".join(unscoped),
                "message": (
                    "La corrida liquida varios CCT "
                    f"({', '.join(sorted(run_agreement_codes))}) y estas "
                    f"fórmulas no tienen convenio asignado ({', '.join(unscoped)}): "
                    "se aplican a todos los convenios; asignar alcance en "
                    "PATCH /api/v1/formulas/{id}/scope."
                ),
            })
    # Gancho de cobertura por CCT: avisa (sin bloquear) cuando el período
    # excede la vigencia del catálogo o el estado no está vigente.
    if agreement_ids:
        warnings.extend(
            _cct_coverage_warnings(
                sorted(set(agreement_codes.values())), _load_catalog_coverage(), period
            )
        )

    # B-27: seal the normative package applied and point the run at it.
    ruleset = _snapshot_ruleset(db, run, formulas, parameters, inputs_hash, period)
    run.ruleset_id = ruleset.id
    # B-36: compact deterministic hash over the per-row hashes, so a paginated
    # response carries the same run hash as the full one.
    run.results_hash = _digest({"results": result_hashes, "errors": errors})
    run.status = "ERROR" if errors else "CALCULATED"
    db.flush()

    return {
        "payroll_run_id": run.id,
        "status": run.status,
        "summary": {
            "employees_total": len(employees) + len(omitted),
            "calculated": calculated_total,
            "errors": len(errors),
            "gross": str(gross_total),
            "net": str(net_total),
        },
        "results": results,
        "results_total": calculated_total,
        "errors": errors,
        "warnings": warnings,
        "inputs_hash": inputs_hash,
        "results_hash": run.results_hash,
        "ruleset_id": run.ruleset_id,
    }


def _semester_bounds(period: date) -> tuple[date, date]:
    """Half-year ``[start, end]`` containing ``period`` (SAC semester)."""

    if period.month <= 6:
        return date(period.year, 1, 1), date(period.year, 6, 30)
    return date(period.year, 7, 1), date(period.year, 12, 31)


def _months_inclusive(start: date, end: date) -> int:
    """Calendar months from ``start`` to ``end`` inclusive (floored at 0)."""

    return max(0, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def _completed_years(start: date, end: date) -> int:
    """Full years of service between two dates."""

    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return max(0, years)


def _prior_monthly_remunerations(
    db: Session,
    *,
    organization_id: int,
    company_id: int,
    employee_id: int,
    semester_start: date,
    cutoff: date,
) -> list[Decimal]:
    """Semester history for SAC: monthly remunerative amounts up to ``cutoff``.

    Only MONTHLY runs with persisted results count; a settlement never feeds
    another settlement (the SAC of a SAC is not a monthly remuneration).
    """

    return list(
        db.scalars(
            select(PayrollResult.remunerative)
            .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
            .where(
                PayrollRun.organization_id == organization_id,
                PayrollRun.company_id == company_id,
                PayrollRun.run_type == "MONTHLY",
                PayrollRun.status.in_(_SAC_HISTORY_STATUSES),
                PayrollResult.employee_id == employee_id,
                PayrollRun.period_start >= semester_start,
                PayrollRun.period_start <= cutoff,
            )
            .order_by(PayrollRun.period_start)
        ).all()
    )


def _settlement_months_worked(hire: date, semester_start: date, end: date) -> int:
    """Accrual months from the later of hire/semester start to ``end`` (cap 6)."""

    start = max(hire, semester_start)
    return min(6, _months_inclusive(date(start.year, start.month, 1), end))


def _novelty_entries(
    novelties: list[dict[str, object]], code: str
) -> list[dict[str, object]]:
    return [entry for entry in novelties if entry.get("code") == code]


def _novelty_decimal(value: object, code: str, field: str) -> Decimal:
    """Coerce a novelty measure to Decimal; anything non-numeric fails."""

    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError(f"La novedad {code} requiere {field} numérico.")
    return Decimal(value)


def _required_novelty_quantity(
    novelties: list[dict[str, object]], code: str
) -> Decimal:
    """Single non-negative quantity novelty; missing/duplicate/negative fails."""

    entries = _novelty_entries(novelties, code)
    if len(entries) != 1:
        raise ValueError(
            f"Se requiere exactamente una novedad {code} en el período."
        )
    value = entries[0].get("quantity")
    if value is None:
        raise ValueError(f"La novedad {code} requiere quantity.")
    amount = _novelty_decimal(value, code, "quantity")
    if amount < 0:
        raise ValueError(f"La novedad {code} no puede ser negativa.")
    return amount


def _compute_sac(
    db: Session,
    *,
    run: PayrollRun,
    employee: Employee,
    base_salary: Decimal,
    hire: date,
    period: date,
) -> tuple[Decimal, list[dict[str, Any]], list[str]]:
    """SAC from semester history (or the current base without history).

    Returns ``(amount, items, trace)``. No novelty is consumed.
    """

    semester_start, _semester_end = _semester_bounds(period)
    history = _prior_monthly_remunerations(
        db,
        organization_id=run.organization_id,
        company_id=run.company_id,
        employee_id=employee.id,
        semester_start=semester_start,
        cutoff=run.period_start,
    )
    remunerations = history if history else [base_salary]
    months = _settlement_months_worked(hire, semester_start, period)
    result = calculate_sac(remunerations, period, months_worked=Decimal(months))
    items = [{
        "code": "SAC",
        "name": "Sueldo anual complementario",
        "nature": ConceptNature.REMUNERATIVE.value,
        "quantity": result.effective_months,
        "unit_value": None,
        "amount": result.amount,
    }]
    return result.amount, items, result.trace


def _compute_vacations(
    *,
    base_salary: Decimal,
    novelties: list[dict[str, object]],
) -> tuple[Decimal, list[dict[str, Any]], list[str], list[str]]:
    """Vacation pay from the VAC_DIAS novelty.

    Returns ``(amount, items, trace, warnings)``. The plus rate comes from an
    optional VAC_PLUS_TASA novelty; omitting it liquidates zero plus with a
    warning (same B-29 spirit as the engine default).
    """

    days = _required_novelty_quantity(novelties, VAC_DAYS_CODE)
    plus_entries = _novelty_entries(novelties, VAC_PLUS_RATE_CODE)
    if len(plus_entries) > 1:
        raise ValueError(
            f"Se requiere como máximo una novedad {VAC_PLUS_RATE_CODE}."
        )
    plus_rate: Decimal | None = None
    if plus_entries:
        raw_amount = plus_entries[0].get("amount")
        if raw_amount is None:
            raise ValueError(f"La novedad {VAC_PLUS_RATE_CODE} requiere amount.")
        amount = _novelty_decimal(raw_amount, VAC_PLUS_RATE_CODE, "amount")
        if amount < 0:
            raise ValueError(f"La novedad {VAC_PLUS_RATE_CODE} no puede ser negativa.")
        plus_rate = amount
    # LCT standard: daily value over 25 days (explicit, not a silent default).
    result = calculate_vacations(
        base_salary, days, days_base=Decimal(25), plus_rate=plus_rate
    )
    items = [{
        "code": "VACACIONES",
        "name": "Vacaciones",
        "nature": ConceptNature.REMUNERATIVE.value,
        "quantity": days,
        "unit_value": result.daily_value,
        "amount": result.amount,
    }]
    return result.amount, items, result.trace, list(result.warnings)


def _compute_final(
    db: Session,
    *,
    run: PayrollRun,
    employee: Employee,
    base_salary: Decimal,
    hire: date,
    termination: date,
    period: date,
    novelties: list[dict[str, object]],
    parameters: dict[str, Decimal],
) -> tuple[Decimal, Decimal, list[dict[str, Any]], list[str]]:
    """Final settlement for a termination inside the run period.

    Returns ``(remunerative, non_remunerative, items, trace)``. The engine
    does not compute contributions or deductions (same contract as the
    /settlements simulation); missing legal parameters are employee errors.
    """

    missing = [code for code in FINAL_PARAMETER_CODES if code not in parameters]
    if missing:
        raise ValueError(
            "Faltan parámetros normativos AR vigentes: "
            f"{', '.join(missing)}."
        )
    engine_parameters = {
        engine_key: parameters[db_code]
        for db_code, engine_key in FINAL_PARAMETER_CODES.items()
    }
    integration_days = _required_novelty_quantity(
        novelties, FINAL_INTEGRATION_DAYS_CODE
    )
    vacation_days = _required_novelty_quantity(novelties, VAC_DAYS_CODE)
    years = _completed_years(hire, termination)
    semester_start, _semester_end = _semester_bounds(termination)
    history = _prior_monthly_remunerations(
        db,
        organization_id=run.organization_id,
        company_id=run.company_id,
        employee_id=employee.id,
        semester_start=semester_start,
        cutoff=termination,
    )
    months = _settlement_months_worked(hire, semester_start, termination)
    result = calculate_final_settlement(
        {
            "period": period,
            "monthly_salary": base_salary,
            "integration_days": integration_days,
            "vacation_days": vacation_days,
            "sac_months_worked": Decimal(months),
            "years_of_service": Decimal(years),
            "seniority_base_salary": base_salary,
            "sac_remunerations": history if history else [base_salary],
        },
        engine_parameters,
    )
    items = [{
        "code": item.code,
        "name": item.name,
        "nature": item.nature.value,
        "quantity": item.quantity,
        "unit_value": None,
        "amount": item.amount,
    } for item in result.items]
    return (
        result.remunerative_total,
        result.non_remunerative_total,
        items,
        result.trace,
    )


def _store_settlement_result(
    db: Session,
    run: PayrollRun,
    *,
    employee: Employee,
    employee_code: str,
    remunerative: Decimal,
    non_remunerative: Decimal,
    items: list[dict[str, Any]],
    trace_lines: list[str],
    concepts: dict[str, PayrollConcept],
    period: date,
) -> str:
    """Persist one settlement result with its items and CALCULATED trace."""

    for item in items:
        if item["code"] not in concepts:
            raise ValueError(
                f"No hay un concepto configurado para {item['code']}."
            )
        if len(str(item["code"])) > 40:
            raise ValueError("El código de un concepto supera los 40 caracteres permitidos.")
    gross = remunerative + non_remunerative
    result = PayrollResult(
        payroll_run_id=run.id,
        employee_id=employee.id,
        remunerative=remunerative,
        non_remunerative=non_remunerative,
        deductions=Decimal("0"),
        contributions=Decimal("0"),
        gross=gross,
        net=gross,
        employer_cost=Decimal("0"),
        calculated_at=datetime.now(UTC),
    )
    db.add(result)
    db.flush()
    for item in items:
        concept = concepts[str(item["code"])]
        db.add(PayrollItem(
            payroll_result_id=result.id,
            concept_id=concept.id,
            code=str(item["code"]),
            description=str(item["name"]),
            nature=str(item["nature"]),
            quantity=item.get("quantity"),
            unit_value=item.get("unit_value"),
            amount=item["amount"],
        ))
    row_hash = _digest({
        "run_type": run.run_type,
        "employee_id": employee.id,
        "remunerative": str(remunerative),
        "non_remunerative": str(non_remunerative),
        "items": [
            {key: str(item.get(key)) for key in ("code", "amount", "quantity")}
            for item in items
        ],
    })
    result.results_hash = row_hash
    db.add(PayrollTrace(
        payroll_result_id=result.id,
        payroll_run_id=run.id,
        employee_id=employee.id,
        event="CALCULATED",
        detail={
            "period": period.isoformat(),
            "run_type": run.run_type,
            "lines": trace_lines,
        },
    ))
    return row_hash


def _load_terminated_population(
    db: Session, run: PayrollRun, period: date
) -> tuple[list[Employee], dict[int, list[EmploymentContract]]]:
    """Employees terminated inside the run period with their contracts.

    Unlike monthly-like runs there is no omitted channel: anyone outside the
    window is simply out of scope for a final settlement.
    """

    employees = db.scalars(
        select(Employee)
        .join(EmploymentContract, EmploymentContract.employee_id == Employee.id)
        .where(
            Employee.organization_id == run.organization_id,
            Employee.termination_date >= run.period_start,
            Employee.termination_date <= period,
            EmploymentContract.company_id == run.company_id,
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= Employee.termination_date,
            or_(
                EmploymentContract.valid_to.is_(None),
                EmploymentContract.valid_to >= Employee.termination_date,
            ),
        )
        .order_by(Employee.id)
    ).unique().all()
    employees = list(employees)
    employee_ids = [employee.id for employee in employees]
    contracts_by_employee: dict[int, list[EmploymentContract]] = {}
    if employee_ids:
        for contract_row in db.scalars(
            select(EmploymentContract).where(
                EmploymentContract.company_id == run.company_id,
                EmploymentContract.employee_id.in_(employee_ids),
                EmploymentContract.active.is_(True),
            )
        ).all():
            contracts_by_employee.setdefault(contract_row.employee_id, []).append(contract_row)
    return employees, contracts_by_employee


def _run_settlement(
    db: Session,
    run: PayrollRun,
    *,
    include_items: bool = True,
    results_limit: int | None = None,
    results_offset: int = 0,
    allow_unconsumed_novelties: bool = False,
) -> dict:
    """Calculate a SAC/VACATIONS/FINAL run with the settlement engine.

    Monthly formulas never run here: SAC is derived from persisted monthly
    history, and VACATIONS/FINAL read per-employee inputs from AUXILIARY
    novelties of the run period (documented codes). Anything missing is a
    per-employee error (fail-closed); unknown novelties follow V2-09.
    Contributions and deductions are not computed (same contract as the
    /settlements simulation), so net equals gross.
    """

    period = run.period_end
    _clear_previous_results(db, run.id)
    parameters = _applicable_parameters(db, period)
    concept_rows = db.scalars(
        select(PayrollConcept).where(
            PayrollConcept.organization_id == run.organization_id,
            PayrollConcept.active.is_(True),
        )
    ).all()
    concepts = {concept.code: concept for concept in concept_rows}

    if run.run_type == "FINAL":
        employees, contracts_by_employee = _load_terminated_population(
            db, run, period
        )
        omitted: list[Employee] = []
    else:
        employees, omitted, contracts_by_employee = _load_active_population(
            db, run, period
        )
    employee_ids = [employee.id for employee in employees]
    novelties_by_employee = _novelties_for_employees(
        db, run.organization_id, employee_ids, period
    )
    _categories, scales_by_category, _agreement_ids, _agreement_codes = (
        _preload_agreement_data(db, contracts_by_employee, period)
    )

    results: list[dict] = []
    errors: list[dict[str, str | int]] = []
    warnings: list[dict[str, str | int]] = []
    input_employees: list[dict] = []
    # B-36: summary accumulators stay complete when the detail is paginated.
    calculated_total = 0
    gross_total = Decimal("0")
    net_total = Decimal("0")
    result_hashes: list[str] = []
    for candidate in omitted:
        errors.append({
            "employee_id": candidate.id,
            "employee_code": candidate.employee_code,
            "message": (
                "El empleado activo no tiene un contrato vigente para la "
                "empresa y el período; quedó fuera de la liquidación."
            ),
        })
        db.add(PayrollTrace(
            payroll_run_id=run.id,
            employee_id=candidate.id,
            event="EMPLOYEE_ERROR",
            detail={"message": (
                "El empleado activo no tiene un contrato vigente para la "
                "empresa y el período; quedó fuera de la liquidación."
            )},
        ))
    for employee in employees:
        employee_contracts = contracts_by_employee.get(employee.id, [])
        valid_contracts = [
            contract_row for contract_row in employee_contracts
            if contract_row.valid_from <= (employee.termination_date or period)
            and (
                contract_row.valid_to is None
                or contract_row.valid_to >= (employee.termination_date or period)
            )
        ] if run.run_type == "FINAL" else employee_contracts
        if len(valid_contracts) != 1:
            errors.append({
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "message": "Se requiere exactamente un contrato vigente para el período.",
            })
            continue
        contract = valid_contracts[0]
        base_salary = _resolve_base_salary(contract, scales_by_category)
        employee_novelties = novelties_by_employee.get(employee.id, [])
        input_employees.append({
            "employee_id": employee.id,
            "contract_id": contract.id,
            "base_salary": base_salary,
            "hire_date": employee.hire_date,
            "termination_date": employee.termination_date,
            "novelties": employee_novelties,
            "settlement": {"run_type": run.run_type},
        })
        try:
            if base_salary is None:
                raise ValueError(
                    "No hay sueldo base: el contrato no fija monthly_salary "
                    "ni hay una escala salarial única vigente."
                )
            if run.run_type == "SAC":
                hire = employee.hire_date or contract.valid_from
                remunerative, items, trace_lines = _compute_sac(
                    db, run=run, employee=employee,
                    base_salary=base_salary, hire=hire,
                    period=period,
                )
                non_remunerative = Decimal("0")
                extra_warnings: list[str] = []
            elif run.run_type == "VACATIONS":
                amount, items, trace_lines, extra_warnings = _compute_vacations(
                    base_salary=base_salary, novelties=employee_novelties,
                )
                remunerative, non_remunerative = amount, Decimal("0")
            else:
                if employee.termination_date is None:
                    raise ValueError(
                        "La liquidación final requiere fecha de desvinculación."
                    )
                hire = employee.hire_date or contract.valid_from
                remunerative, non_remunerative, items, trace_lines = _compute_final(
                    db, run=run, employee=employee,
                    base_salary=base_salary, hire=hire,
                    termination=employee.termination_date,
                    period=period, novelties=employee_novelties,
                    parameters=parameters,
                )
                extra_warnings = []
            for extra in extra_warnings:
                warnings.append({
                    "type": "settlement_warning",
                    "employee_id": employee.id,
                    "employee_code": employee.employee_code,
                    "code": run.run_type,
                    "message": extra,
                })
            row_hash = _store_settlement_result(
                db, run,
                employee=employee,
                employee_code=employee.employee_code,
                remunerative=remunerative,
                non_remunerative=non_remunerative,
                items=items,
                trace_lines=trace_lines,
                concepts=concepts,
                period=period,
            )
        except (ArithmeticError, LookupError, TypeError, ValueError) as exc:
            message = str(exc)
            errors.append({
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "message": message,
            })
            db.add(PayrollTrace(
                payroll_run_id=run.id,
                employee_id=employee.id,
                event="EMPLOYEE_ERROR",
                detail={"message": message},
            ))
            continue

        # V2-09: novelties consumed by no settlement input are errors by
        # default, warnings only under the explicit opt-out flag.
        for code in sorted(
            {str(entry.get("code")) for entry in employee_novelties}
            - SETTLEMENT_CONSUMED_CODES[run.run_type]
        ):
            entry: dict[str, str | int] = {
                "type": "novelty_not_consumed",
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "code": code,
                "message": (
                    f"La novedad {code} del período no fue consumida "
                    "por ninguna liquidación."
                ),
            }
            if allow_unconsumed_novelties:
                warnings.append(entry)
            else:
                errors.append(entry)
                db.add(PayrollTrace(
                    payroll_run_id=run.id,
                    employee_id=employee.id,
                    event="NOVELTY_NOT_CONSUMED",
                    detail={"message": entry["message"], "code": code},
                ))
        # B-36: every row is persisted, but only the requested window is
        # serialized into the response; totals below always cover everyone.
        slot = calculated_total
        calculated_total += 1
        gross_total += remunerative + non_remunerative
        net_total += remunerative + non_remunerative
        result_hashes.append(row_hash)
        if (
            include_items
            and slot >= results_offset
            and (results_limit is None or len(results) < results_limit)
        ):
            results.append({
                "employee_id": employee.id,
                "remunerative": str(remunerative),
                "non_remunerative": str(non_remunerative),
                "deductions": "0",
                "contributions": "0",
                "gross": str(remunerative + non_remunerative),
                "net": str(remunerative + non_remunerative),
                "employer_cost": "0",
                "items": [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "nature": item["nature"],
                        "amount": str(item["amount"]),
                        "quantity": (
                            None if item.get("quantity") is None
                            else str(item["quantity"])
                        ),
                        "unit_value": (
                            None if item.get("unit_value") is None
                            else str(item["unit_value"])
                        ),
                    }
                    for item in items
                ],
                "trace": trace_lines,
            })

    inputs_hash = _digest({
        "run_id": run.id,
        "company_id": run.company_id,
        "period_start": run.period_start,
        "period_end": run.period_end,
        "run_type": run.run_type,
        "employees": input_employees,
        "parameters": parameters,
    })
    run.inputs_hash = inputs_hash
    # B-27: seal the applied inputs even without formulas so reliquidating an
    # old period with rewritten parameters cannot silently change history.
    ruleset = _snapshot_ruleset(db, run, [], parameters, inputs_hash, period)
    run.ruleset_id = ruleset.id
    # B-36: compact deterministic hash over the per-row hashes, so a paginated
    # response carries the same run hash as the full one.
    run.results_hash = _digest({"results": result_hashes, "errors": errors})
    run.status = "ERROR" if errors else "CALCULATED"
    db.flush()

    return {
        "payroll_run_id": run.id,
        "status": run.status,
        "summary": {
            "employees_total": len(employees) + len(omitted),
            "calculated": calculated_total,
            "errors": len(errors),
            "gross": str(gross_total),
            "net": str(net_total),
        },
        "results": results,
        "results_total": calculated_total,
        "errors": errors,
        "warnings": warnings,
        "inputs_hash": inputs_hash,
        "results_hash": run.results_hash,
        "ruleset_id": run.ruleset_id,
    }


__all__ = [
    "FINAL_INTEGRATION_DAYS_CODE",
    "FINAL_PARAMETER_CODES",
    "PayrollRunStateError",
    "SETTLEMENT_CONCEPT_CODES",
    "SETTLEMENT_CONSUMED_CODES",
    "SETTLEMENT_RUN_TYPES",
    "VAC_DAYS_CODE",
    "VAC_PLUS_RATE_CODE",
    "calculate_payroll_run",
]
