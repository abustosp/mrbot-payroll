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
    PayrollSettlementInput,
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
            "SAC", "VACACIONES", "SUELDO_DIAS", "PREAVISO", "INTEGRACION_MES",
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
        if run_type in {"SAC", "VACATIONS", "FINAL"}:
            for code, employee in context["employees"].items():
                salary = "600000" if code == "E-2" else "1200000"
                values = {"sac_excluded_days": 0, "vacation_base_salary": salary}
                if run_type == "FINAL":
                    values.update(cause="DESPIDO_SIN_CAUSA", worked_days="20", worked_base_salary=salary,
                        notice_base_salary=salary, vacation_days="14", other_entitlements_reviewed=True,
                        probation=False, without_notice=True, preaviso_months="2", integration_days=10,
                        indemnity_base_salary=salary, indemnity_cap=salary)
                session.add(PayrollSettlementInput(payroll_run_id=run.id, employee_id=employee.id, values=values))
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
    for month in (1, 2, 6):
        _add_monthly_history(factory, context, "E-1", date(2026, month, 1), "900000")
    _add_novelty(factory, context, "E-2", "SAC_BASE", "202606", amount="600000")
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
        "gross": "634806.63", "net": "634806.63",
    }
    by_employee = {row["employee_id"]: row for row in result["results"]}
    e1 = context["employees"]["E-1"].id
    e2 = context["employees"]["E-2"].id
    # E-1: mejor 1200000 / 12 * 6 meses.
    assert by_employee[e1]["gross"] == "600000.00"
    assert by_employee[e1]["employer_cost"] == "600000.00"
    with factory() as session:
        from sqlalchemy import select

        stored = session.scalar(select(PayrollResult).where(
            PayrollResult.payroll_run_id == run_id, PayrollResult.employee_id == e1
        ))
        assert stored is not None and stored.employer_cost == stored.gross
    # E-2: 21 días calendario de los 181 días del semestre.
    assert by_employee[e2]["gross"] == "34806.63"


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
    _add_novelty(factory, context, "E-1", "SAC_BASE", "202606", amount="1200000")
    _add_novelty(factory, context, "E-2", "SAC_BASE", "202606", amount="600000")
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
    _add_novelty(factory, context, "E-1", "VAC_PLUS_TASA", "202606", amount="0")
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

    _add_novelty(factory, context, "E-3", "SAC_BASE", "202606", amount="1000000")
    run_id = _create_run(
        factory, context, "final", "FINAL", date(2026, 6, 1), date(2026, 6, 30)
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "CALCULATED", result["errors"]
    assert result["summary"]["employees_total"] == 1
    row = result["results"][0]
    # 7 años indemnizables: seis completos y fracción mayor a tres meses.
    assert row["gross"] == "13144375.69"
    assert row["remunerative"] == "1272375.69"
    assert row["non_remunerative"] == "11872000.00"
    assert [item["code"] for item in row["items"]] == [
        "SUELDO_DIAS", "PREAVISO", "INTEGRACION_MES", "VACACIONES_NO_GOZADAS",
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
                NormativeParameter.code == "liq_vacaciones_dias_base"
            )
        )

    run_id = _create_run(
        factory, context, "final-sin-param", "FINAL",
        date(2026, 6, 1), date(2026, 6, 30),
    )
    result = _calculate(factory, run_id)

    assert result["status"] == "ERROR"
    assert any(
        "liq_vacaciones_dias_base" in error["message"] for error in result["errors"]
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
    _add_novelty(factory, context, "E-1", "SAC_BASE", "202606", amount="1200000")
    _add_novelty(factory, context, "E-2", "SAC_BASE", "202606", amount="600000")
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


def test_sac_calendar_days_and_explicit_base(settlement_db):
    from app.core.payroll_engine.settlements import calculate_sac
    from app.services.payroll_calculation import _sac_inputs
    factory, context = settlement_db
    for hire, end, amount, expected in (
        (date(2025, 11, 6), date(2025, 12, 31), "6900", "1050.00"),
        (date(2025, 2, 10), date(2025, 6, 30), "20000", "7790.06"),
    ):
        with factory() as session:
            run = PayrollRun(organization_id=context["organization_id"], company_id=context["company_id"],
                             run_type="SAC", period_start=end, period_end=end, status="DRAFT", code="temporary")
            employee = session.get(Employee, context["employees"]["E-1"].id)
            history, best, months, trace = _sac_inputs(session, run=run, employee=employee, hire=hire, end=end,
                novelties=[{"code": "SAC_BASE", "kind": "AUXILIARY", "amount": Decimal(amount)}])
            assert calculate_sac(history, end, months_worked=months, best_salary=best).amount == Decimal(expected)
            assert any("faltantes=" in line and "días=" in trace[0] for line in trace)


def test_empty_runs_are_errors(settlement_db):
    from sqlalchemy import select

    from app.database.models import PayrollTrace
    factory, context = settlement_db
    with factory.begin() as session:
        company = Company(organization_id=context["organization_id"], cuit="30567890199", legal_name="Sin empleados")
        session.add(company)
        session.flush()
        context = {**context, "company_id": company.id}
    for kind in ("MONTHLY", "SAC", "VACATIONS", "FINAL"):
        run_id = _create_run(factory, context, "empty-" + kind, kind, date(2028, 1, 1), date(2028, 1, 31))
        result = _calculate(factory, run_id)
        assert result["status"] == "ERROR"
        with factory() as session:
            events = session.scalars(select(PayrollTrace.event).where(PayrollTrace.payroll_run_id == run_id)).all()
            assert "RUN_ERROR" in events and "CALCULATION_REVIEW" in events


def test_special_rules_are_explicit_scoped_and_snapshotted(settlement_db):
    from app.database.models import FormulaDefinition, FormulaVersion, Ruleset
    factory, context = settlement_db
    with factory.begin() as session:
        contract = session.query(EmploymentContract).filter_by(employee_id=context["employees"]["E-1"].id).one()
        contract.agreement_id = session.get(AgreementCategory, contract.category_id).agreement_id
        for code, nature, rate, condition, scope in (
            ("VAC_APORTE", "DEDUCTION", "0.10", "VACATIONS", None),
            ("VAC_PATRONAL", "CONTRIBUTION", "0.20", "VACATIONS", None),
            ("OTRO_CCT", "DEDUCTION", "0.50", "VACATIONS", "NO-APLICA"),
            ("CCT_APORTE", "DEDUCTION", "0.01", "VACATIONS", "999/99"),
            ("MENSUAL", "REMUNERATIVE", "1", "MONTHLY", None),
        ):
            session.add(PayrollConcept(organization_id=context["organization_id"], code=code, name=code, nature=nature))
            definition = FormulaDefinition(organization_id=context["organization_id"], code=code, agreement_code=scope)
            session.add(definition)
            session.flush()
            session.add(FormulaVersion(formula_id=definition.id, version=1, status="APPROVED", valid_from=date(2026, 1, 1),
                expression={"operator": "multiply", "arguments": [{"parameter": "settlement_remunerative"}, {"constant": rate}]},
                conditions=[{"field": "run_type", "operator": "eq", "value": condition}]))
    for employee in ("E-1", "E-2"):
        _add_novelty(factory, context, employee, "VAC_DIAS", "202606", quantity="5")
        _add_novelty(factory, context, employee, "VAC_PLUS_TASA", "202606", amount="0")
    run_id = _create_run(factory, context, "special-rules", "VACATIONS", date(2026, 6, 1), date(2026, 6, 30))
    result = _calculate(factory, run_id)
    assert result["status"] == "CALCULATED", result["errors"]
    row = next(row for row in result["results"] if row["employee_id"] == context["employees"]["E-1"].id)
    assert (row["gross"], row["deductions"], row["contributions"], row["net"], row["employer_cost"]) == (
        "240000.00", "26400.00", "48000.00", "213600.00", "288000.00")
    assert {item["code"] for item in row["items"]} == {"VACACIONES", "VAC_APORTE", "VAC_PATRONAL", "CCT_APORTE"}
    with factory() as session:
        snapshot = session.get(Ruleset, result["ruleset_id"]).rules
        assert {f["code"] for f in snapshot["formulas"]} == {"VAC_APORTE", "VAC_PATRONAL", "OTRO_CCT", "CCT_APORTE"}
        assert snapshot["parameter_versions"]


def test_final_reports_terminated_without_contract(settlement_db):
    from sqlalchemy import select

    from app.database.models import PayrollTrace
    factory, context = settlement_db
    with factory.begin() as session:
        employee = Employee(organization_id=context["organization_id"], employee_code="SIN-CONT",
                            first_name="Sin", last_name="Contrato", hire_date=date(2020, 1, 1),
                            termination_date=date(2026, 6, 15), active=False)
        session.add(employee)
        session.flush()
        employee_id = employee.id
    run_id = _create_run(factory, context, "final-sin-contrato", "FINAL", date(2026, 6, 1), date(2026, 6, 30))
    result = _calculate(factory, run_id)
    assert result["status"] == "ERROR"
    assert any(error.get("employee_id") == employee_id and "contrato" in error["message"] for error in result["errors"])
    with factory() as session:
        assert session.scalar(select(PayrollTrace.id).where(PayrollTrace.payroll_run_id == run_id,
            PayrollTrace.employee_id == employee_id, PayrollTrace.event == "EMPLOYEE_ERROR")) is not None


def test_sac_missing_history_reports_months(settlement_db):
    factory, context = settlement_db
    _add_monthly_history(factory, context, "E-1", date(2026, 3, 1), "900000")
    run_id = _create_run(factory, context, "incomplete-history", "SAC", date(2026, 6, 1), date(2026, 6, 30))
    result = _calculate(factory, run_id)
    assert result["status"] == "ERROR"
    error = next(error for error in result["errors"] if error["employee_id"] == context["employees"]["E-1"].id)
    assert "2026-01" in error["message"] and "SAC_BASE" in error["message"]


def test_final_cause_caps_and_unpaid_leave(settlement_db):
    from app.services.payroll_calculation import _compute_final
    from app.services.settlement_inputs import SettlementInputs
    factory, context = settlement_db
    base = dict(cause="RENUNCIA", worked_days="20", worked_base_salary="1200000",
                vacation_days="10", vacation_base_salary="1500000", sac_excluded_days=10,
                other_entitlements_reviewed=True)
    with factory() as db:
        employee = db.get(Employee, context["employees"]["E-3"].id)
        run = PayrollRun(organization_id=context["organization_id"], company_id=context["company_id"],
            run_type="FINAL", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), status="DRAFT", code="x")
        args = dict(db=db, run=run, employee=employee, base_salary=Decimal("1200000"),
            hire=date(2020, 3, 15), termination=date(2026, 6, 20), period=date(2026, 6, 30),
            novelties=[{"code": "SAC_BASE", "kind": "AUXILIARY", "amount": Decimal("1200000")}],
            parameters={"liq_vacaciones_dias_base": Decimal(25), "liq_vacaciones_plus_tasa": Decimal(0)})
        _, _, items, trace = _compute_final(**args, inputs=SettlementInputs(**base))
        by_code = {i["code"]: i for i in items}
        assert set(by_code) == {"SUELDO_DIAS", "SAC_PROPORCIONAL", "VACACIONES_NO_GOZADAS"}
        assert by_code["VACACIONES_NO_GOZADAS"]["amount"] == Decimal("600000.00")
        assert by_code["SAC_PROPORCIONAL"]["amount"] == Decimal("533701.66")
        assert any("excluidos=10" in line for line in trace)
        dismissal = SettlementInputs(**(base | dict(cause="DESPIDO_SIN_CAUSA", probation=False,
            without_notice=True, preaviso_months="2", integration_days=10, notice_base_salary="1200000",
            indemnity_base_salary="1200000", indemnity_cap="400000")))
        _, _, items, _ = _compute_final(**args, inputs=dismissal)
        by_code = {i["code"]: i for i in items}
        assert by_code["INDEMNIZACION_ANTIGUEDAD"]["amount"] == Decimal("5628000.00")
        assert by_code["INDEMNIZACION_ANTIGUEDAD"]["quantity"] == 7
        assert by_code["PREAVISO"]["amount"] == Decimal("2400000.00")
        args["termination"] = date(2026, 6, 15)
        dismissal = dismissal.model_copy(update={"integration_days": 15, "worked_days": Decimal(15)})
        _, _, items, _ = _compute_final(**args, inputs=dismissal)
        assert next(i for i in items if i["code"] == "INDEMNIZACION_ANTIGUEDAD")["quantity"] == 6
        with pytest.raises(ValueError, match="integración"):
            _compute_final(**args, inputs=dismissal.model_copy(update={"integration_days": 0}))
        with pytest.raises(ValueError, match="causa"):
            _compute_final(**args, inputs=SettlementInputs())


def test_settlement_input_api_scope_csrf_audit_and_immutability(settlement_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.settlements import router
    from app.auth.security import sign_session
    from app.config import get_settings
    from app.database.models import AuditLog
    from app.database.session import get_db
    from app.web.auth import create_csrf_token
    factory, context = settlement_db
    run_id = _create_run(factory, context, "input-api", "SAC", date(2026, 6, 1), date(2026, 6, 30))
    employee_id = context["employees"]["E-1"].id
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    def db_override():
        with factory() as db:
            yield db
    application.dependency_overrides[get_db] = db_override
    settings = get_settings()
    with TestClient(application) as client:
        client.cookies.set(settings.session_cookie, sign_session(context["admin_id"], settings.secret_key))
        url = f"/api/v1/settlements/runs/{run_id}/employees/{employee_id}/inputs"
        assert client.put(url, json={"sac_excluded_days": 5}).status_code == 403
        csrf = create_csrf_token(settings.secret_key, context["admin_id"])
        client.cookies.set("payroll_csrf", csrf)
        headers = {"X-CSRF-Token": csrf}
        assert client.put(url, json={"sac_excluded_days": 5}, headers=headers).status_code == 200
        assert client.get(url).json()["sac_excluded_days"] == 5
        assert client.put(url.replace(f"employees/{employee_id}", "employees/999999"),
                          json={"sac_excluded_days": 5}, headers=headers).status_code == 404
        with factory.begin() as db:
            db.get(PayrollRun, run_id).status = "APPROVED"
            assert db.query(AuditLog).filter_by(action="settlement_inputs.updated").count() == 1
        assert client.put(url, json={"sac_excluded_days": 0}, headers=headers).status_code == 409
