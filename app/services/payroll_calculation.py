"""Persist deterministic payroll calculations for one payroll run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.payroll_engine.calculator import _definition_applies, calculate_payroll
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
    if run.run_type != "MONTHLY":
        # B-10: filas preexistentes con run_type especial no se liquidan como
        # mensuales en silencio (la API ya los rechaza con 422 al crear).
        raise PayrollRunStateError(
            f"run_type {run.run_type!r} no soportado; solo se liquida MONTHLY."
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
    employee_ids = [employee.id for employee in employees]
    # B-17: activos de la organización sin contrato vigente para la empresa y
    # el período. El join de arriba los excluye en silencio; se listan en el
    # canal de errores para que la nómina incompleta no parezca completa.
    included_ids = set(employee_ids)
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
            EmploymentContract.employee_id.in_(employee_ids),
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= period,
            or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= period),
        )
    ).all() if employee_ids else []
    contracts_by_employee: dict[int, list[EmploymentContract]] = {}
    for contract_row in contracts:
        contracts_by_employee.setdefault(contract_row.employee_id, []).append(contract_row)
    novelties_by_employee = _novelties_for_employees(
        db, run.organization_id, employee_ids, period
    )
    # B-35: categories, scales and agreement codes are preloaded with one
    # query each instead of one query per employee (N+1).
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
        base_salary = (
            contract.monthly_salary
            if contract.monthly_salary is not None
            else (scale.base_salary + scale.additional if scale is not None else None)
        )

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


__all__ = ["PayrollRunStateError", "calculate_payroll_run"]
