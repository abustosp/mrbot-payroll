from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.config import Settings
from app.database import Base
from app.database.models import PayrollRun
from app.services.payroll_calculation import calculate_payroll_run
from app.web.demo_data import DemoDataStore
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
        calculate_payroll_run(session, run)
        run_id = run.id
        company_id = company.id

    source = SqlAlchemyDataSource(factory)
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
        with pytest.raises(ValueError, match="No hay propuestas IA persistidas"):
            source.set_proposal_status("1", "approved")

        receipts = source.list_receipts()
        assert len(receipts) == 2
        assert all(receipt.status == "pending" for receipt in receipts)
        assert source.get_receipt(receipts[0].id) == receipts[0]
        assert source.receipt_periods() == [("2026-06", "Junio 2026")]
        assert receipts[0].to_pdf_context()["items"]
    finally:
        engine.dispose()


def test_web_source_setting_defaults_to_demo_and_can_select_sql(monkeypatch) -> None:
    monkeypatch.delenv("PAYROLL_WEB_DATA_SOURCE", raising=False)
    assert Settings(_env_file=None).web_data_source == "demo"

    monkeypatch.setenv("PAYROLL_WEB_DATA_SOURCE", "sql")
    assert Settings(_env_file=None).web_data_source == "sql"
    monkeypatch.setattr(main, "get_settings", lambda: Settings(web_data_source="sql"))
    sql_app = main.create_app()
    assert isinstance(sql_app.state.payroll_data_source, SqlAlchemyDataSource)

    monkeypatch.delenv("PAYROLL_WEB_DATA_SOURCE")
    monkeypatch.setattr(main, "get_settings", lambda: Settings())
    demo_app = main.create_app()
    with TestClient(demo_app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Modo demo" in response.text
    assert isinstance(demo_app.state.payroll_data_source, DemoDataStore)
