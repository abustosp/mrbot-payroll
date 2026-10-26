"""Service-level payroll calculation tests for applicable rules and errors."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.models import (
    Employee,
    FormulaDefinition,
    FormulaVersion,
    PayrollConcept,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    PayrollTrace,
)
from app.services.payroll_calculation import calculate_payroll_run
from scripts.seed_demo import seed


@pytest.fixture
def payroll_db(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker[Session], dict[str, object]], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll-service.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        context: dict[str, object] = {
            "organization_id": demo["organization"].id,
            "company_id": demo["company"].id,
            "admin_id": demo["admin"].id,
            "employee_ids": [employee.id for employee in demo["employees"]],
        }
    yield factory, context
    engine.dispose()


def _create_run(
    factory: sessionmaker[Session], context: dict[str, object]
) -> int:
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="service-test",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        return run.id


def _calculate(
    factory: sessionmaker[Session], run_id: int
) -> dict[str, object]:
    with factory.begin() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        return calculate_payroll_run(session, run)


def test_validated_only_formula_is_not_applied(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    factory, context = payroll_db
    with factory.begin() as session:
        concept = PayrollConcept(
            organization_id=context["organization_id"],
            code="EXTRA",
            name="Concepto extra",
            nature="REMUNERATIVE",
        )
        session.add(concept)
        session.flush()
        formula = FormulaDefinition(
            organization_id=context["organization_id"],
            code="EXTRA",
            description="Sólo validada",
            current_version=1,
        )
        session.add(formula)
        session.flush()
        session.add(
            FormulaVersion(
                formula_id=formula.id,
                version=1,
                expression={"constant": "500000.00"},
                status="VALIDATED",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
            )
        )

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    results = result["results"]
    assert isinstance(results, list)
    assert len(results) == 2
    assert all("EXTRA" not in line for row in results for line in row["trace"])
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PayrollItem)
                .where(PayrollItem.code == "EXTRA")
            )
            == 0
        )


def test_terminated_employee_is_excluded_even_when_active(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    factory, context = payroll_db
    employee_ids = context["employee_ids"]
    assert isinstance(employee_ids, list)
    with factory.begin() as session:
        terminated = session.get(Employee, employee_ids[0])
        still_on_period_end = session.get(Employee, employee_ids[1])
        assert terminated is not None and still_on_period_end is not None
        terminated.termination_date = date(2026, 5, 31)
        terminated.active = True
        still_on_period_end.termination_date = date(2026, 6, 30)
        still_on_period_end.active = True

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    assert result["summary"]["employees_total"] == 1
    assert result["summary"]["calculated"] == 1
    assert [row["employee_id"] for row in result["results"]] == [employee_ids[1]]


def test_highest_approved_version_wins_in_calculation(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    factory, context = payroll_db
    with factory.begin() as session:
        formula = session.scalar(
            select(FormulaDefinition).where(
                FormulaDefinition.organization_id == context["organization_id"],
                FormulaDefinition.code == "BASICO",
            )
        )
        assert formula is not None
        session.add(
            FormulaVersion(
                formula_id=formula.id,
                version=2,
                expression={"constant": "777.00"},
                status="APPROVED",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                approved_by=context["admin_id"],
            )
        )
        formula.current_version = 2

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    basico_amounts = [
        item["amount"]
        for row in result["results"]
        for item in row["items"]
        if item["code"] == "BASICO"
    ]
    assert basico_amounts == ["777.00", "777.00"]
    with factory() as session:
        trace = session.scalar(
            select(PayrollTrace).where(PayrollTrace.event == "CALCULATED")
        )
        assert trace is not None
        versions = {
            entry["code"]: entry["version"]
            for entry in trace.detail["formula_versions"]
        }
        assert versions["BASICO"] == 2


def test_negative_net_is_reported_per_employee_before_persisting(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    factory, context = payroll_db
    with factory.begin() as session:
        formula = session.scalar(
            select(FormulaDefinition).where(
                FormulaDefinition.organization_id == context["organization_id"],
                FormulaDefinition.code == "JUBILACION",
            )
        )
        assert formula is not None
        version = session.scalar(
            select(FormulaVersion).where(
                FormulaVersion.formula_id == formula.id,
                FormulaVersion.version == 1,
            )
        )
        assert version is not None
        version.expression = {"constant": "99999999.00"}

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "ERROR"
    assert result["results"] == []
    errors = result["errors"]
    assert len(errors) == 2
    assert all("neto negativo" in error["message"] for error in errors)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PayrollResult)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(PayrollTrace)
                .where(PayrollTrace.event == "EMPLOYEE_ERROR")
            )
            == 2
        )
