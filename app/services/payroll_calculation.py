"""Persist deterministic payroll calculations for one payroll run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.payroll_engine.calculator import calculate_payroll
from app.core.payroll_engine.types import (
    ConceptNature,
    FormulaStatus,
)
from app.core.payroll_engine.types import (
    FormulaDefinition as FormulaContract,
)
from app.database.models import (
    AgreementCategory,
    Employee,
    EmploymentContract,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    PayrollTrace,
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
            FormulaVersion.status.in_(("VALIDATED", "APPROVED")),
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
        definitions.append(
            FormulaContract(
                code=formula.code,
                description=formula.description or concept.name,
                formula=version.expression,
                nature=ConceptNature(concept.nature),
                valid_from=version.valid_from,
                valid_to=version.valid_to,
                status=FormulaStatus(version.status),
                version=version.version,
                source=f"formula_version:{version.id}",
            )
        )
    if not definitions:
        raise ValueError("No hay fórmulas validadas o aprobadas vigentes para el período.")
    return definitions


def calculate_payroll_run(db: Session, run: PayrollRun) -> dict:
    """Calculate eligible employees and replace all results already stored for ``run``."""

    if run.status not in {"DRAFT", "CALCULATED", "IN_REVIEW", "ERROR"}:
        raise PayrollRunStateError("No se puede calcular una liquidación aprobada o cerrada.")

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

    employees = db.scalars(
        select(Employee)
        .join(EmploymentContract, EmploymentContract.employee_id == Employee.id)
        .where(
            Employee.organization_id == run.organization_id,
            Employee.active.is_(True),
            EmploymentContract.company_id == run.company_id,
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= period,
            or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= period),
        )
        .order_by(Employee.id)
    ).unique().all()
    employee_ids = [employee.id for employee in employees]
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

    results: list[dict] = []
    errors: list[dict[str, str | int]] = []
    input_employees: list[dict] = []
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
            category = db.get(AgreementCategory, contract.category_id)
            scales = db.scalars(
                select(SalaryScale).where(
                    SalaryScale.category_id == contract.category_id,
                    SalaryScale.valid_from <= period,
                    or_(SalaryScale.valid_to.is_(None), SalaryScale.valid_to >= period),
                ).order_by(SalaryScale.valid_from.desc())
            ).all()
            if len(scales) == 1:
                scale = scales[0]
        base_salary = (
            contract.monthly_salary
            if contract.monthly_salary is not None
            else (scale.base_salary + scale.additional if scale is not None else None)
        )

        input_employees.append({
            "employee_id": employee.id,
            "contract_id": contract.id,
            "category_id": contract.category_id,
            "scale_id": scale.id if scale else None,
            "category_code": category.code if category else None,
            "base_salary": base_salary,
            "scale_additional": scale.additional if scale else None,
            "hire_date": employee.hire_date,
            "contract_valid_from": contract.valid_from,
            "contract_valid_to": contract.valid_to,
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
            definitions = _definitions_for_employee(formulas, concepts)
            calculated = calculate_payroll(
                {
                    "id": employee.id,
                    "base_salary": base_salary,
                    "start_date": employee.hire_date or contract.valid_from,
                    "agreement_category": category.code,
                },
                period,
                definitions,
                parameters,
            )
            if any(len(item.code) > 40 for item in calculated.items):
                raise ValueError("El código de un concepto supera los 40 caracteres permitidos.")
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
            results_hash=_digest(serialized),
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
    run.results_hash = _digest({"results": results, "errors": errors})
    run.status = "ERROR" if errors else "CALCULATED"
    db.flush()

    return {
        "payroll_run_id": run.id,
        "status": run.status,
        "summary": {
            "employees_total": len(employees),
            "calculated": len(results),
            "errors": len(errors),
            "gross": str(sum((Decimal(result["gross"]) for result in results), Decimal("0"))),
            "net": str(sum((Decimal(result["net"]) for result in results), Decimal("0"))),
        },
        "results": results,
        "errors": errors,
        "inputs_hash": inputs_hash,
        "results_hash": run.results_hash,
    }


__all__ = ["PayrollRunStateError", "calculate_payroll_run"]
