from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import app.main as main
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    AgreementCategory,
    AiProposal,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    Organization,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    SalaryScale,
    User,
)
from app.services.payroll_calculation import calculate_payroll_run
from app.web.auth import WebUser
from app.web.demo_data import DemoDataStore
from app.web.routes import _request_data_source
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def test_sql_data_source_maps_seed_and_calculated_payroll(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-data.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        company = demo["company"]
        admin = demo["admin"]
        run = PayrollRun(
            organization_id=demo["organization"].id,
            company_id=company.id,
            code="web-june-2026",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="DRAFT",
            created_by=admin.id,
        )
        session.add(run)
        session.flush()
        run_id = run.id
        company_id = company.id
        organization_id = demo["organization"].id
    # NOTE (B-13): calculate_payroll_run commits its VALIDATING state, so it
    # cannot run inside an explicit transaction block.
    with factory() as session:
        stored = session.get(PayrollRun, run_id)
        assert stored is not None
        calculate_payroll_run(session, stored)
        session.commit()

    source = SqlAlchemyDataSource(factory, organization_id)
    try:
        assert source.is_demo is False
        assert source.source_name == "Base de datos SQL"
        assert "propuestas" in source.explanation

        companies = source.list_companies()
        assert len(companies) == 1
        assert companies[0].id == str(company_id)
        assert companies[0].employee_count == 2
        assert companies[0].agreement == "CCT 130/75"
        assert source.get_company(str(company_id)) == companies[0]

        employees = source.list_employees()
        assert len(employees) == 2
        assert {employee.company_id for employee in employees} == {str(company_id)}
        assert all(employee.salary > Decimal("0") for employee in employees)
        assert len(source.employees_for_company(str(company_id))) == 2
        assert source.get_employee(employees[0].id) is not None

        agreements = source.list_agreements()
        assert len(agreements) == 1
        assert agreements[0].code == "CCT 130/75"
        assert len(agreements[0].categories) == 2
        assert source.get_agreement(agreements[0].id) == agreements[0]

        payrolls = source.list_payrolls()
        assert len(payrolls) == 1
        assert payrolls[0].id == str(run_id)
        assert payrolls[0].status == "calculated"
        assert payrolls[0].employee_count == 2
        assert payrolls[0].gross > 0 and payrolls[0].net > 0
        assert payrolls[0].concepts
        assert source.get_payroll(str(run_id)) == payrolls[0]

        metrics = source.dashboard_metrics()
        assert metrics["companies"] == 1
        assert metrics["active_employees"] == 2
        assert metrics["in_review"] == 1
        assert metrics["pending_proposals"] == 0
        assert metrics["latest_payroll"].id == str(run_id)
        assert metrics["total_net"] > 0 and metrics["total_gross"] > 0

        assert source.list_proposals() == []
        assert source.get_proposal("1") is None
        assert source.set_proposal_status("1", "approved") is None
        with pytest.raises(ValueError, match="Estado de propuesta no valido"):
            source.set_proposal_status("1", "invented")

        receipts = source.list_receipts()
        assert len(receipts) == 2
        assert all(receipt.status == "pending" for receipt in receipts)
        assert source.get_receipt(receipts[0].id) == receipts[0]
        assert source.receipt_periods() == [("2026-06", "Junio 2026")]
        assert receipts[0].to_pdf_context()["items"]
    finally:
        engine.dispose()


def test_sql_lists_filter_in_sql_and_paginate(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-pagination.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        org = _seed_organization(
            session,
            slug="pagination",
            name="Paginación",
            cuit="30733333336",
            employee_code="P-001",
            cuil="20333333331",
            agreement_code="CCT-P",
            run_code="run-p",
            net="100000.00",
        )
        category = session.scalar(
            select(AgreementCategory).where(
                AgreementCategory.agreement_id == org["agreement_id"]
            )
        )
        assert category is not None
        for index, code in enumerate(("P-002", "P-003"), start=2):
            amount = Decimal(f"{index}00000.00")
            employee = Employee(
                organization_id=org["organization_id"],
                employee_code=code,
                first_name="Empleado",
                last_name=f"Paginado {index}",
                cuil=f"2033333333{index}",
                hire_date=date(2024, 1, 1),
                active=True,
            )
            session.add(employee)
            session.flush()
            session.add(
                EmploymentContract(
                    employee_id=employee.id,
                    company_id=org["company_id"],
                    agreement_id=org["agreement_id"],
                    category_id=category.id,
                    valid_from=date(2024, 1, 1),
                    active=True,
                    monthly_salary=amount,
                )
            )
            result = PayrollResult(
                payroll_run_id=org["run_id"],
                employee_id=employee.id,
                remunerative=amount,
                non_remunerative=Decimal("0"),
                deductions=Decimal("100.00"),
                contributions=Decimal("0"),
                gross=amount + Decimal("100.00"),
                net=amount,
                employer_cost=amount + Decimal("100.00"),
            )
            session.add(result)
            session.flush()
            session.add(
                PayrollItem(
                    payroll_result_id=result.id,
                    code="BASICO",
                    description="Sueldo básico",
                    nature="REMUNERATIVE",
                    quantity=Decimal("1"),
                    unit_value=amount,
                    amount=amount,
                )
            )

    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    source = SqlAlchemyDataSource(factory, org["organization_id"])
    try:
        employees = source.list_employees()
        assert len(employees) == 3
        assert source.list_employees(status="active") == employees
        assert source.list_employees(status="inactive") == []
        assert source.list_employees(status="bogus") == []
        assert source.list_employees(company_id=str(org["company_id"])) == employees
        assert source.list_employees(company_id="999999") == []
        assert [employee.id for employee in source.list_employees(query="paginado 2")] == [
            employee.id for employee in employees if employee.file_number == "P-002"
        ]

        first = source.list_employees(limit=2)
        rest = source.list_employees(limit=2, offset=2)
        assert len(first) == 2
        assert len(rest) == 1
        assert {employee.id for employee in first} | {employee.id for employee in rest} == {
            employee.id for employee in employees
        }
        assert source.list_employees(limit=1, offset=9) == []

        receipts = source.list_receipts()
        assert len(receipts) == 3
        assert source.list_receipts(status="issued") == receipts
        assert source.list_receipts(status="pending") == []
        assert source.list_receipts(status="bogus") == []
        assert source.list_receipts(period="2026-09") == receipts
        assert source.list_receipts(period="1999-01") == []
        assert source.list_receipts(period="nope") == []
        assert source.list_receipts(company_id=str(org["company_id"])) == receipts
        assert source.list_receipts(query="paginado 3") != []

        first_receipts = source.list_receipts(limit=2)
        rest_receipts = source.list_receipts(limit=2, offset=2)
        assert len(first_receipts) == 2
        assert len(rest_receipts) == 1
        assert {receipt.id for receipt in first_receipts} | {
            receipt.id for receipt in rest_receipts
        } == {receipt.id for receipt in receipts}

        # Los filtros estructurados y la paginación se aplican en SQL.
        statements.clear()
        source.list_employees(company_id=str(org["company_id"]), limit=1)
        assert any("LIMIT" in statement.upper() for statement in statements)
        statements.clear()
        source.list_receipts(period="2026-09", limit=1)
        assert any("LIMIT" in statement.upper() for statement in statements)
    finally:
        engine.dispose()


def test_sql_data_source_isolates_organizations(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-isolation.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        org_a = _seed_organization(
            session,
            slug="organization-a",
            name="Organización A",
            cuit="30711111118",
            employee_code="A-001",
            cuil="20111111112",
            agreement_code="CCT-A",
            run_code="run-a",
            net="100000.00",
        )
        org_b = _seed_organization(
            session,
            slug="organization-b",
            name="Organización B",
            cuit="30722222227",
            employee_code="B-001",
            cuil="20222222223",
            agreement_code="CCT-B",
            run_code="run-b",
            net="900000.00",
        )

    source_a = SqlAlchemyDataSource(factory, org_a["organization_id"])
    source_b = SqlAlchemyDataSource(factory, org_b["organization_id"])
    unscoped = SqlAlchemyDataSource(factory)
    try:
        companies_a = source_a.list_companies()
        assert [company.id for company in companies_a] == [str(org_a["company_id"])]
        assert source_a.get_company(str(org_b["company_id"])) is None
        assert source_a.get_company(str(org_a["company_id"])) is not None

        employees_a = source_a.list_employees()
        assert [employee.id for employee in employees_a] == [str(org_a["employee_id"])]
        assert source_a.list_employees(company_id=str(org_b["company_id"])) == []
        assert source_a.employees_for_company(str(org_b["company_id"])) == []
        assert source_a.get_employee(str(org_b["employee_id"])) is None

        agreements_a = source_a.list_agreements()
        assert [agreement.id for agreement in agreements_a] == [str(org_a["agreement_id"])]
        assert source_a.get_agreement(str(org_b["agreement_id"])) is None
        assert source_a.get_agreement(str(org_a["agreement_id"])) is not None

        payrolls_a = source_a.list_payrolls()
        assert [payroll.id for payroll in payrolls_a] == [str(org_a["run_id"])]
        assert source_a.list_payrolls(company_id=str(org_b["company_id"])) == []
        assert source_a.get_payroll(str(org_b["run_id"])) is None

        receipts_a = source_a.list_receipts()
        assert [receipt.id for receipt in receipts_a] == [str(org_a["result_id"])]
        assert receipts_a[0].company_id == str(org_a["company_id"])
        assert source_a.list_receipts(company_id=str(org_b["company_id"])) == []
        assert source_a.list_receipts(period="2026-09") == receipts_a
        assert source_a.get_receipt(str(org_b["result_id"])) is None
        assert source_a.receipt_periods() == [("2026-09", "Septiembre 2026")]

        proposals_a = source_a.list_proposals()
        assert [proposal.id for proposal in proposals_a] == [str(org_a["proposal_id"])]
        assert proposals_a[0].status == "draft"
        assert proposals_a[0].title == "Propuesta Organización A"
        assert proposals_a[0].agreement == "CCT-A"
        assert proposals_a[0].source_page == "Artículo 1, página 3"
        assert source_a.list_proposals(status="approved") == []
        assert source_a.get_proposal(str(org_b["proposal_id"])) is None
        assert source_a.set_proposal_status(str(org_b["proposal_id"]), "approved") is None
        with factory() as session:
            assert session.get(AiProposal, org_b["proposal_id"]).status == "draft"
        metrics_before_update = source_a.dashboard_metrics()
        assert metrics_before_update["pending_proposals"] == 1
        updated = source_a.set_proposal_status(str(org_a["proposal_id"]), "approved")
        assert updated is not None and updated.status == "approved"
        with factory() as session:
            assert session.get(AiProposal, org_b["proposal_id"]).status == "draft"

        metrics_a = source_a.dashboard_metrics()
        metrics_b = source_b.dashboard_metrics()
        assert metrics_a["companies"] == 1
        assert metrics_a["active_employees"] == 1
        assert metrics_a["in_review"] == 0
        assert metrics_a["pending_proposals"] == 0
        assert metrics_b["pending_proposals"] == 1
        assert metrics_a["issued_receipts"] == 1
        assert metrics_a["latest_payroll"].id == str(org_a["run_id"])
        assert metrics_a["total_net"] == Decimal("100000.00")
        assert metrics_b["total_net"] == Decimal("900000.00")
        assert metrics_a["total_net"] != metrics_b["total_net"]

        # A source without a resolved organization must never project all rows.
        assert unscoped.list_companies() == []
        assert unscoped.list_employees() == []
        assert unscoped.list_agreements() == []
        assert unscoped.list_payrolls() == []
        assert unscoped.list_receipts() == []
        assert unscoped.list_proposals() == []
        assert unscoped.dashboard_metrics()["companies"] == 0
        assert unscoped.dashboard_metrics()["latest_payroll"] is None
    finally:
        engine.dispose()


def _seed_organization(
    session,
    *,
    slug: str,
    name: str,
    cuit: str,
    employee_code: str,
    cuil: str,
    agreement_code: str,
    run_code: str,
    net: str,
) -> dict[str, int]:
    amount = Decimal(net)
    deductions = Decimal("100.00")
    gross = amount + deductions

    organization = Organization(name=name, slug=slug)
    agreement = CollectiveAgreement(
        code=agreement_code,
        year=2026,
        name=f"Convenio {name}",
        scope="Convenio de prueba",
    )
    session.add_all([organization, agreement])
    session.flush()

    user = User(
        organization_id=organization.id,
        email=f"{slug}@example.test",
        password_hash="not-used-in-this-test",
        role="admin",
    )
    category = AgreementCategory(
        agreement_id=agreement.id,
        code="A",
        name=f"Categoría {name}",
    )
    company = Company(
        organization_id=organization.id,
        cuit=cuit,
        legal_name=f"Empresa {name}",
        tax_activity="Servicios",
        address="Calle 1, Ciudad",
        active=True,
    )
    session.add_all([user, category, company])
    session.flush()

    session.add(
        SalaryScale(
            category_id=category.id,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            base_salary=amount,
            additional=Decimal("0"),
        )
    )
    employee = Employee(
        organization_id=organization.id,
        employee_code=employee_code,
        first_name="Empleado",
        last_name=name,
        cuil=cuil,
        hire_date=date(2024, 1, 1),
        active=True,
    )
    session.add(employee)
    session.flush()

    contract = EmploymentContract(
        employee_id=employee.id,
        company_id=company.id,
        agreement_id=agreement.id,
        category_id=category.id,
        valid_from=date(2024, 1, 1),
        active=True,
        monthly_salary=amount,
    )
    run = PayrollRun(
        organization_id=organization.id,
        company_id=company.id,
        code=run_code,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        run_type="MONTHLY",
        status="APPROVED",
        created_by=user.id,
    )
    session.add_all([contract, run])
    session.flush()

    result = PayrollResult(
        payroll_run_id=run.id,
        employee_id=employee.id,
        remunerative=amount,
        non_remunerative=Decimal("0"),
        deductions=deductions,
        contributions=Decimal("0"),
        gross=gross,
        net=amount,
        employer_cost=gross,
    )
    session.add(result)
    session.flush()

    session.add(
        PayrollItem(
            payroll_result_id=result.id,
            code="BASICO",
            description="Sueldo básico",
            nature="REMUNERATIVE",
            quantity=Decimal("1"),
            unit_value=amount,
            amount=amount,
        )
    )
    proposal = AiProposal(
        organization_id=organization.id,
        document_id=f"doc-{slug}",
        title=f"Propuesta {name}",
        raw_json={
            "summary": f"Resumen de {name}",
            "agreement_number": agreement_code,
            "agreement_title": f"Convenio {name}",
            "formulas": [
                {
                    "code": "BASICO",
                    "description": f"Fórmula de {name}",
                    "source": {
                        "document_id": f"doc-{slug}",
                        "version": "1",
                        "page": 3,
                        "article": "Artículo 1",
                    },
                }
            ],
            "ambiguities": [f"Advertencia de {name}"],
        },
        validation_json={"is_valid": True, "reports": []},
        status="draft",
    )
    session.add(proposal)
    session.flush()

    return {
        "organization_id": organization.id,
        "company_id": company.id,
        "employee_id": employee.id,
        "agreement_id": agreement.id,
        "run_id": run.id,
        "result_id": result.id,
        "proposal_id": proposal.id,
    }


def test_web_source_setting_defaults_to_demo_and_can_select_sql(monkeypatch) -> None:
    monkeypatch.delenv("PAYROLL_WEB_DATA_SOURCE", raising=False)
    assert Settings(_env_file=None).web_data_source == "demo"

    monkeypatch.setenv("PAYROLL_WEB_DATA_SOURCE", "sql")
    assert Settings(_env_file=None).web_data_source == "sql"
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(web_data_source="sql", web_auth_enabled=False),
    )
    sql_app = main.create_app()
    assert isinstance(sql_app.state.payroll_data_source, SqlAlchemyDataSource)
    monkeypatch.delenv("PAYROLL_WEB_AUTH_ENABLED", raising=False)
    assert Settings(_env_file=None).web_auth_enabled is True

    monkeypatch.delenv("PAYROLL_WEB_DATA_SOURCE")
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(web_auth_enabled=False),
    )
    demo_app = main.create_app()
    demo_app.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    with TestClient(demo_app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Modo demo" in response.text
    assert isinstance(demo_app.state.payroll_data_source, DemoDataStore)


def test_request_data_source_fails_closed_without_organization(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-no-org.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        _seed_organization(
            session,
            slug="organization-a",
            name="Organización A",
            cuit="30711111118",
            employee_code="A-001",
            cuil="20111111112",
            agreement_code="CCT-A",
            run_code="run-a",
            net="100000.00",
        )

    source = SqlAlchemyDataSource(factory)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
        }
    )
    user = WebUser(id=999999, email="orphan@example.test", role="admin")
    try:
        with factory() as session:
            scoped = _request_data_source(request, user, session, source)

        assert scoped is not source
        assert scoped.organization_id == -1
        assert scoped.list_companies() == []
        assert scoped.list_employees() == []
        assert scoped.list_payrolls() == []
        assert scoped.dashboard_metrics()["companies"] == 0
        assert request.state.payroll_data_source is scoped
    finally:
        engine.dispose()
