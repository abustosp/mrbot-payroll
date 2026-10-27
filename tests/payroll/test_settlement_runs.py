"""Settlement run types: SAC from history, VACATIONS/FINAL from novelties."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    NormativeParameter,
    Organization,
    PayrollConcept,
    PayrollNovelty,
    PayrollResult,
    PayrollRun,
    SalaryScale,
    User,
)
from app.services.payroll_calculation import calculate_payroll_run


@pytest.fixture
def settlement_db(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker[Session], dict[str, Any]], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'settlement.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        organization = Organization(name="Org Liquidaciones", slug="set")
        session.add(organization)
        session.flush()
        admin = User(
            organization_id=organization.id,
            email="admin@example.com",
            password_hash="x",
            role="admin",
        )
        session.add(admin)
        company = Company(
            organization_id=organization.id,
            cuit="30567890123",
            legal_name="Empresa 1",
        )
        session.add(company)
        session.flush()
        agreement = CollectiveAgreement(
            code="999/99", year=2026, name="Convenio de prueba"
        )
        session.add(agreement)
        session.flush()
        category = AgreementCategory(
            agreement_id=agreement.id,
            code="CAT-A",
            name="Categoria A",
        )
        session.add(category)
        session.flush()
        session.add(SalaryScale(
            category_id=category.id,
            base_salary=Decimal("1000000"),
            additional=Decimal("0"),
            valid_from=date(2026, 1, 1),
        ))
        employees = {}
        for code, first, hire, termination, salary in (
            ("E-1", "Ana", date(2024, 1, 15), None, "1200000"),
            ("E-2", "Beto", date(2026, 6, 10), None, "600000"),
            ("E-3", "Cora", date(2020, 3, 15), date(2026, 6, 20), "1200000"),
        ):
            employee = Employee(
                organization_id=organization.id,
                employee_code=code,
                first_name=first,
                last_name="Prueba",
                hire_date=hire,
                termination_date=termination,
                active=True,
            )
            session.add(employee)
            session.flush()
            session.add(EmploymentContract(
                employee_id=employee.id,
                company_id=company.id,
                category_id=category.id,
                valid_from=hire,
                monthly_salary=Decimal(salary),
                active=True,
            ))
            employees[code] = employee
        for concept_code in (
            "SAC", "VACACIONES", "PREAVISO", "INTEGRACION_MES",
            "VACACIONES_NO_GOZADAS", "SAC_PROPORCIONAL",
            "INDEMNIZACION_ANTIGUEDAD",
        ):
            session.add(PayrollConcept(
                organization_id=organization.id,
                code=concept_code,
                name=concept_code,
                nature="REMUNERATIVE",
            ))
        for param_code, value in (
            ("liq_preaviso_meses", "1"),
            ("liq_integracion_dias_base", "30"),
            ("liq_vacaciones_dias_base", "25"),
            ("liq_vacaciones_plus_tasa", "0"),
            ("liq_antiguedad_meses_por_anio", "1"),
        ):
            session.add(NormativeParameter(
                jurisdiction="AR",
                code=param_code,
                value=Decimal(value),
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                version=1,
            ))
        session.flush()
        context: dict[str, Any] = {
            "organization_id": organization.id,
            "company_id": company.id,
            "admin_id": admin.id,
            "employees": employees,
        }
    yield factory, context
    engine.dispose()


def _create_run(
    factory: sessionmaker[Session],
    context: dict[str, Any],
    code: str,
    run_type: str,
    start: date,
    end: date,
) -> int:
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code=code,
            period_start=start,
            period_end=end,
            run_type=run_type,
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        return run.id


def _calculate(
    factory: sessionmaker[Session], run_id: int, **kwargs: Any
) -> dict[str, Any]:
    # NOTE (B-13): calculate_payroll_run commits its VALIDATING state, so it
    # cannot run inside an explicit transaction block.
    with factory() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        try:
            result = calculate_payroll_run(session, run, **kwargs)
        except Exception:
            session.rollback()
            raise
        session.commit()
        return result


def _add_monthly_history(
    factory: sessionmaker[Session],
    context: dict[str, Any],
    employee_code: str,
    period: date,
    remunerative: str,
) -> None:
    with factory.begin() as session:
        employee = context["employees"][employee_code]
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code=f"hist-{period.isoformat()}",
            period_start=period,
            period_end=period,
            run_type="MONTHLY",
            status="CALCULATED",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        session.add(PayrollResult(
            payroll_run_id=run.id,
            employee_id=employee.id,
            remunerative=Decimal(remunerative),
            non_remunerative=Decimal("0"),
            deductions=Decimal("0"),
            contributions=Decimal("0"),
            gross=Decimal(remunerative),
            net=Decimal(remunerative),
            employer_cost=Decimal("0"),
        ))


def _add_novelty(
    factory: sessionmaker[Session],
    context: dict[str, Any],
    employee_code: str,
    code: str,
    period: str,
    quantity: str | None = None,
    amount: str | None = None,
) -> None:
    with factory.begin() as session:
        session.add(PayrollNovelty(
            organization_id=context["organization_id"],
            employee_id=context["employees"][employee_code].id,
            period=period,
            code=code,
            kind="AUXILIARY",
            quantity=Decimal(quantity) if quantity is not None else None,
            amount=Decimal(amount) if amount is not None else None,
            source="test",
        ))


def test_sac_uses_best_semester_remuneration(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """SAC: mejor remuneración del semestre / 12 * meses (historial)."""
    factory, context = settlement_db
    _add_monthly_history(factory, context, "E-1", date(2026, 3, 1), "900000")
    _add_monthly_history(factory, context, "E-1", date(2026, 4, 1), "1200000")
    _add_monthly_history(factory, context, "E-1", date(2026, 5, 1), "1100000")

    run_id = _create_run(
        factory, context, "sac-h1", "SAC", date(2026, 6, 1), date(2026, 6, 30)
    )
    result = _calculate(factory, run_id)

    # E-3 está desvinculado el 20/06 y no integra la corrida mensual de
    # junio (su SAC proporcional va en la liquidación final).
    assert result["status"] == "CALCULATED", result["errors"]
    assert result["summary"] == {
        "employees_total": 2, "calculated": 2, "errors": 0,
        "gross": "650000.00", "net": "650000.00",
    }
    by_employee = {row["employee_id"]: row for row in result["results"]}
    e1 = context["employees"]["E-1"].id
    e2 = context["employees"]["E-2"].id
    # E-1: mejor 1200000 / 12 * 6 meses.
    assert by_employee[e1]["gross"] == "600000.00"
    # E-2: sin historial, base actual 600000, 1 mes (junio).
    assert by_employee[e2]["gross"] == "50000.00"


def test_sac_ignores_non_monthly_history(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """Un SAC previo no alimenta la base de otro SAC."""
    factory, context = settlement_db
    with factory.begin() as session:
        employee = context["employees"]["E-1"]
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="sac-previo",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            run_type="SAC",
            status="CALCULATED",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        session.add(PayrollResult(
            payroll_run_id=run.id,
            employee_id=employee.id,
            remunerative=Decimal("5000000"),
            non_remunerative=Decimal("0"),
            deductions=Decimal("0"),
            contributions=Decimal("0"),
            gross=Decimal("5000000"),
            net=Decimal("5000000"),
            employer_cost=Decimal("0"),
        ))
    run_id = _create_run(
        factory, context, "sac-h1b", "SAC", date(2026, 6, 1), date(2026, 6, 30)
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "CALCULATED", result["errors"]
    by_employee = {row["employee_id"]: row for row in result["results"]}
    # Sin historial mensual: base 1200000 / 12 * 6, no 5000000 del SAC previo.
    assert by_employee[context["employees"]["E-1"].id]["gross"] == "600000.00"


def test_vacations_from_novelty_days(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """Vacaciones: días por novedad VAC_DIAS; plus opcional por VAC_PLUS_TASA."""
    factory, context = settlement_db
    _add_novelty(factory, context, "E-1", "VAC_DIAS", "202606", quantity="10")
    _add_novelty(factory, context, "E-2", "VAC_DIAS", "202606", quantity="10")
    _add_novelty(
        factory, context, "E-2", "VAC_PLUS_TASA", "202606", amount="0.10"
    )

    run_id = _create_run(
        factory, context, "vac", "VACATIONS", date(2026, 6, 1), date(2026, 6, 30)
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "CALCULATED", result["errors"]
    by_employee = {row["employee_id"]: row for row in result["results"]}
    # E-1: 1200000 / 25 * 10, sin plus (aviso, no error).
    assert by_employee[context["employees"]["E-1"].id]["gross"] == "480000.00"
    # E-2: 600000 / 25 * 10 = 240000 + 10% = 264000.
    assert by_employee[context["employees"]["E-2"].id]["gross"] == "264000.00"
    assert any(
        warning["type"] == "settlement_warning"
        for warning in result["warnings"]
    )


def test_vacations_without_days_is_employee_error(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """Sin VAC_DIAS el empleado va al canal de errores (fail-closed)."""
    factory, context = settlement_db
    run_id = _create_run(
        factory, context, "vac-vacia", "VACATIONS",
        date(2026, 6, 1), date(2026, 6, 30),
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "ERROR"
    assert result["summary"]["calculated"] == 0
    assert any(
        "VAC_DIAS" in error["message"] for error in result["errors"]
    )


def test_final_settlement_terminated_only(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """FINAL: solo desvinculados en el período; los activos no molestan."""
    factory, context = settlement_db
    _add_monthly_history(factory, context, "E-3", date(2026, 3, 1), "1000000")
    _add_novelty(factory, context, "E-3", "VAC_DIAS", "202606", quantity="14")
    _add_novelty(
        factory, context, "E-3", "LIQ_DIAS_INTEGRACION", "202606", quantity="10"
    )

    run_id = _create_run(
        factory, context, "final", "FINAL", date(2026, 6, 1), date(2026, 6, 30)
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "CALCULATED", result["errors"]
    assert result["summary"]["employees_total"] == 1
    row = result["results"][0]
    # PREAVISO 1200000 + INTEGRACION 400000 + VACACIONES 672000
    # + SAC 500000 + ANTIGUEDAD 7200000 = 9972000.
    assert row["gross"] == "9972000.00"
    assert row["remunerative"] == "2772000.00"
    assert row["non_remunerative"] == "7200000.00"
    assert [item["code"] for item in row["items"]] == [
        "PREAVISO", "INTEGRACION_MES", "VACACIONES_NO_GOZADAS",
        "SAC_PROPORCIONAL", "INDEMNIZACION_ANTIGUEDAD",
    ]


def test_final_without_legal_parameters_is_employee_error(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """Sin parámetros liq_* vigentes, error por empleado que nombra el faltante."""
    factory, context = settlement_db
    with factory.begin() as session:
        session.execute(
            NormativeParameter.__table__.delete().where(
                NormativeParameter.code == "liq_preaviso_meses"
            )
        )
    _add_novelty(factory, context, "E-3", "VAC_DIAS", "202606", quantity="14")
    _add_novelty(
        factory, context, "E-3", "LIQ_DIAS_INTEGRACION", "202606", quantity="10"
    )

    run_id = _create_run(
        factory, context, "final-sin-param", "FINAL",
        date(2026, 6, 1), date(2026, 6, 30),
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "ERROR"
    assert any(
        "liq_preaviso_meses" in error["message"] for error in result["errors"]
    )


def test_settlement_unconsumed_novelty_follows_v209(
    settlement_db: tuple[sessionmaker[Session], dict[str, Any]],
) -> None:
    """Novedad ajena en corrida SAC: error por defecto, aviso con opt-out."""
    factory, context = settlement_db
    _add_novelty(
        factory, context, "E-1", "HORAS_EXTRA", "202606",
        quantity="5", amount="10000",
    )
    run_id = _create_run(
        factory, context, "sac-novedad", "SAC",
        date(2026, 6, 1), date(2026, 6, 30),
    )

    strict = _calculate(factory, run_id)
    assert strict["status"] == "ERROR"
    assert {
        error["code"] for error in strict["errors"]
        if error["type"] == "novelty_not_consumed"
    } == {"HORAS_EXTRA"}

    allowed = _calculate(factory, run_id, allow_unconsumed_novelties=True)
    assert allowed["status"] == "CALCULATED"
    assert {
        warning["code"] for warning in allowed["warnings"]
        if warning["type"] == "novelty_not_consumed"
    } == {"HORAS_EXTRA"}
