"""Service-level payroll calculation tests for applicable rules and errors."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
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
    # NOTE (B-13): calculate_payroll_run commits its VALIDATING state, so it
    # cannot run inside an explicit transaction block.
    with factory() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        try:
            result = calculate_payroll_run(session, run)
        except Exception:
            session.rollback()
            raise
        session.commit()
        return result


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


def test_scale_base_and_additional_travel_as_distinct_variables(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-02: la parte NR de la escala llega como variable propia para que las
    # fórmulas la compongan por separado en vez de aportar sobre el total.
    from app.database.models import AgreementCategory, SalaryScale

    factory, context = payroll_db
    with factory.begin() as session:
        session.add(
            PayrollConcept(
                organization_id=context["organization_id"],
                code="NR_ADIC",
                name="Adicional no remunerativo de escala",
                nature="NON_REMUNERATIVE",
            )
        )
        session.flush()
        formula = FormulaDefinition(
            organization_id=context["organization_id"],
            code="NR_ADIC",
            description="Lee la parte NR de la escala",
            current_version=1,
        )
        session.add(formula)
        session.flush()
        session.add(
            FormulaVersion(
                formula_id=formula.id,
                version=1,
                expression={"variable": "escala_adicional"},
                status="APPROVED",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                approved_by=context["admin_id"],
            )
        )
        category = session.scalar(
            select(AgreementCategory).where(AgreementCategory.code == "ADMIN_A")
        )
        assert category is not None
        scale = session.scalar(
            select(SalaryScale).where(SalaryScale.category_id == category.id)
        )
        assert scale is not None
        scale.additional = scale.base_salary * Decimal("0") + Decimal("145000.00")

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    amounts = {
        row["employee_id"]: next(
            item["amount"] for item in row["items"] if item["code"] == "NR_ADIC"
        )
        for row in result["results"]
    }
    assert sorted(amounts.values()) == ["0.00", "145000.00"]


def test_conditional_formula_is_evaluated_by_the_service(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-07: las conditions/rounding/depends_on aprobados deben llegar al
    # cálculo; sin presentismo el concepto da 0, no 80000.
    from app.database.models import PayrollNovelty

    factory, context = payroll_db
    employee_ids = context["employee_ids"]
    assert isinstance(employee_ids, list)
    with factory.begin() as session:
        session.add(
            PayrollConcept(
                organization_id=context["organization_id"],
                code="PRESENTISMO",
                name="Presentismo condicional",
                nature="REMUNERATIVE",
            )
        )
        session.flush()
        formula = FormulaDefinition(
            organization_id=context["organization_id"],
            code="PRESENTISMO",
            description="Solo con asistencia perfecta",
            current_version=1,
        )
        session.add(formula)
        session.flush()
        session.add(
            FormulaVersion(
                formula_id=formula.id,
                version=1,
                expression={"constant": "80000.00"},
                conditions=[
                    {"field": "presentismo", "operator": "greater_than", "value": 0}
                ],
                depends_on=[],
                rounding={"decimals": 2, "mode": "HALF_UP"},
                status="APPROVED",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                approved_by=context["admin_id"],
            )
        )
        for employee_id in employee_ids:
            session.add(
                PayrollNovelty(
                    organization_id=context["organization_id"],
                    employee_id=employee_id,
                    period="202606",
                    code="presentismo",
                    kind="REMUNERATIVE",
                    quantity=Decimal("0"),
                    source="test",
                )
            )

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    amounts = [
        item["amount"]
        for row in result["results"]
        for item in row["items"]
        if item["code"] == "PRESENTISMO"
    ]
    assert amounts == ["0.00", "0.00"]


def test_recalculation_while_validating_is_rejected(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-13: un segundo cálculo concurrente ve VALIDATING y recibe 409 en vez
    # de pisar el primero.
    from app.services.payroll_calculation import PayrollRunStateError

    factory, context = payroll_db
    run_id = _create_run(factory, context)
    with factory.begin() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        run.status = "VALIDATING"
    with factory() as session:
        stored = session.get(PayrollRun, run_id)
        assert stored is not None
        with pytest.raises(PayrollRunStateError, match="en cálculo"):
            calculate_payroll_run(session, stored)
        assert stored.status == "VALIDATING"


def test_failed_recalculation_stays_retryable(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # B-13: si el cálculo revienta a mitad de camino, la corrida queda en
    # ERROR (reintentable) en vez de atascada en VALIDATING.
    from app.services import payroll_calculation as pc

    factory, context = payroll_db
    run_id = _create_run(factory, context)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("fallo simulado a mitad del cálculo")

    monkeypatch.setattr(pc, "calculate_payroll", _boom)
    with factory() as session:
        stored = session.get(PayrollRun, run_id)
        assert stored is not None
        with pytest.raises(RuntimeError, match="fallo simulado"):
            pc.calculate_payroll_run(session, stored)
    with factory() as session:
        stored = session.get(PayrollRun, run_id)
        assert stored is not None
        assert stored.status == "ERROR"


def test_unsupported_run_type_is_rejected_before_calculating(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-10: filas preexistentes con run_type especial no se liquidan como
    # mensuales en silencio.
    from app.services.payroll_calculation import PayrollRunStateError

    factory, context = payroll_db
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="legacy-sac",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="SAC",
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        run_id = run.id
    with factory() as session:
        stored = session.get(PayrollRun, run_id)
        assert stored is not None
        with pytest.raises(PayrollRunStateError, match="run_type"):
            calculate_payroll_run(session, stored)


def test_active_employee_without_contract_is_listed(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-17: el activo importado sin contrato no queda fuera en silencio.
    from app.database.models import Employee

    factory, context = payroll_db
    with factory.begin() as session:
        session.add(
            Employee(
                organization_id=context["organization_id"],
                employee_code="E-090",
                first_name="Sin",
                last_name="Contrato",
                hire_date=date(2024, 1, 15),
                active=True,
            )
        )

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "ERROR"
    assert result["summary"]["employees_total"] == 3
    assert result["summary"]["calculated"] == 2
    omitted = [
        error for error in result["errors"] if error["employee_code"] == "E-090"
    ]
    assert len(omitted) == 1
    assert "contrato" in omitted[0]["message"]


def test_unconsumed_novelty_is_listed_as_warning(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
) -> None:
    # B-11: la novedad que ninguna fórmula consume se avisa en vez de
    # pasar en silencio.
    from app.database.models import PayrollNovelty

    factory, context = payroll_db
    employee_ids = context["employee_ids"]
    assert isinstance(employee_ids, list)
    with factory.begin() as session:
        session.add(
            PayrollNovelty(
                organization_id=context["organization_id"],
                employee_id=employee_ids[0],
                period="202606",
                code="horas_extra",
                kind="REMUNERATIVE",
                quantity=Decimal("5"),
                amount=Decimal("10000"),
                source="test",
            )
        )

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    warnings = result["warnings"]
    assert {
        warning["code"] for warning in warnings if warning["type"] == "novelty_not_consumed"
    } == {"horas_extra"}
    assert all(
        warning["employee_id"] == employee_ids[0] for warning in warnings
    )


def test_cct_out_of_coverage_is_warned_not_blocked(
    payroll_db: tuple[sessionmaker[Session], dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Gancho de cobertura: período fuera de vigencia o estado no vigente
    # avisa en warnings sin frenar la liquidación.
    from app.services import payroll_calculation as pc

    factory, context = payroll_db
    monkeypatch.setattr(
        pc,
        "_load_catalog_coverage",
        lambda: {"130/75": {"vigencia_hasta": "2026-05-31", "status": "stale"}},
    )

    result = _calculate(factory, _create_run(factory, context))

    assert result["status"] == "CALCULATED"
    coverage = [
        warning for warning in result["warnings"] if warning["type"] == "cct_coverage"
    ]
    assert {warning["code"] for warning in coverage} == {"130/75"}
    assert len(coverage) == 2  # vigencia excedida + estado no vigente


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
