"""Focused pins for the motor fixes: V2-09/25/26/27/29, B-26R/29R/36P."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.settlements import FinalSettlementRequest, SacInput, VacationInput
from app.database import Base
from app.database.models import (
    AuditLog,
    CollectiveAgreement,
    EmploymentContract,
    PayrollNovelty,
)
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed


@pytest.fixture
def env(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker[Session], dict[str, Any]], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'motor-v2.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        context = seed(session)

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            )
            assert login.status_code == 200, login.text
            yield client, factory, context
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _create_run(client: TestClient, company_id: int, code: str) -> int:
    response = client.post(
        "/api/v1/payroll-runs",
        json={
            "company_id": company_id,
            "code": code,
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_v209_orphan_novelty_is_error_by_default(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """V2-09: huérfana → ERROR; con flag explícito → aviso y CALCULATED."""
    client, factory, context = env
    company_id = context["company"].id
    employee_id = context["employees"][0].id
    organization_id = context["organization"].id
    with factory.begin() as session:
        session.add(PayrollNovelty(
            organization_id=organization_id, employee_id=employee_id,
            period="202606", code="horas_extra", kind="REMUNERATIVE",
            quantity=Decimal("5"), amount=Decimal("10000"), source="test",
        ))
    run_id = _create_run(client, company_id, "v209-strict")

    strict = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
    assert strict.status_code == 200, strict.text
    assert strict.json()["status"] == "ERROR"
    assert {
        error["code"] for error in strict.json()["errors"]
        if error["type"] == "novelty_not_consumed"
    } == {"horas_extra"}

    allowed = client.post(
        f"/api/v1/payroll-runs/{run_id}/calculate",
        params={"allow_unconsumed_novelties": "true"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "CALCULATED"
    assert {
        warning["code"] for warning in allowed.json()["warnings"]
        if warning["type"] == "novelty_not_consumed"
    } == {"horas_extra"}


def test_b26_multi_cct_without_scope_warns(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """B-26R: corrida multi-CCT con fórmulas sin scope avisa sin bloquear."""
    client, factory, context = env
    company_id = context["company"].id
    second_employee_id = context["employees"][1].id
    with factory.begin() as session:
        other = CollectiveAgreement(code="40/89", year=1989, name="Second agreement")
        session.add(other)
        session.flush()
        contract = session.scalar(
            select(EmploymentContract)
            .where(EmploymentContract.employee_id == second_employee_id)
        )
        assert contract is not None
        contract.agreement_id = other.id
    run_id = _create_run(client, company_id, "b26-multi-cct")

    response = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CALCULATED"
    assert any(
        warning["type"] == "multi_cct_no_scope"
        for warning in response.json()["warnings"]
    )


def test_b26_multi_cct_warning_names_unscoped_formulas(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """B-26R: el aviso multi-CCT identifica las fórmulas sin alcance."""
    client, factory, context = env
    company_id = context["company"].id
    second_employee_id = context["employees"][1].id
    with factory.begin() as session:
        other = CollectiveAgreement(code="40/89", year=1989, name="Second agreement")
        session.add(other)
        session.flush()
        contract = session.scalar(
            select(EmploymentContract)
            .where(EmploymentContract.employee_id == second_employee_id)
        )
        assert contract is not None
        contract.agreement_id = other.id
    run_id = _create_run(client, company_id, "b26-multi-cct-codes")

    response = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
    assert response.status_code == 200, response.text
    scoped_warnings = [
        warning for warning in response.json()["warnings"]
        if warning["type"] == "multi_cct_no_scope"
    ]
    assert scoped_warnings, "se esperaba el aviso multi_cct_no_scope"
    assert "BASICO" in scoped_warnings[0]["codes"]
    assert "scope" in scoped_warnings[0]["message"]


def test_b36_calculate_defaults_to_limit_50() -> None:
    """B-36P: el detalle default pagina a 50 sin recortar el resumen."""
    spec = TestClient(app).get("/openapi.json").json()
    operation = spec["paths"]["/api/v1/payroll-runs/{run_id}/calculate"]["post"]
    defaults = {
        parameter["name"]: parameter["schema"].get("default")
        for parameter in operation.get("parameters", [])
    }
    assert defaults.get("results_limit") == 50


def test_b29_explicit_zero_plus_warns_on_api(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """B-29R: plus 0 explícito liquida 0 con aviso."""
    client, _factory, _context = env
    response = client.post(
        "/api/v1/settlements/vacations",
        json={"monthly_salary": "750000", "days": "10", "plus_rate": "0"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["plus_amount"] == "0.00"
    assert any("plus_rate" in warning for warning in response.json()["warnings"])


def test_v225_reopen_returns_to_draft_with_audit(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """V2-25: CALCULATED→DRAFT auditado; DRAFT y APPROVED no reabren."""
    client, factory, context = env
    company_id = context["company"].id
    organization_id = context["organization"].id
    run_id = _create_run(client, company_id, "v225-reopen")
    assert client.post(f"/api/v1/payroll-runs/{run_id}/reopen").status_code == 409

    assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 200
    reopened = client.post(f"/api/v1/payroll-runs/{run_id}/reopen")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "DRAFT"
    with factory() as session:
        entry = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "payroll_run.reopened",
                AuditLog.entity_id == str(run_id),
            )
        )
        assert entry is not None
        assert entry.before == {"status": "CALCULATED"}
        assert entry.after == {"status": "DRAFT"}
        assert entry.organization_id == organization_id

    assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 200
    assert client.post(f"/api/v1/payroll-runs/{run_id}/approve").status_code == 200
    assert client.post(f"/api/v1/payroll-runs/{run_id}/reopen").status_code == 409


def test_v226_contract_create_validates_overlap_and_validity(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """V2-26: alta 201, solape 409, vigencia 422, ausentes 404/422."""
    client, _factory, context = env
    company_id = context["company"].id
    employee_id = context["employees"][0].id
    base = {"employee_id": employee_id, "company_id": company_id}

    created = client.post(
        "/api/v1/contracts",
        json={**base, "valid_from": "2010-01-01", "valid_to": "2010-12-31"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["employee_id"] == employee_id

    overlap = client.post(
        "/api/v1/contracts",
        json={**base, "valid_from": "2026-01-01"},
    )
    assert overlap.status_code == 409, overlap.text

    invalid = client.post(
        "/api/v1/contracts",
        json={**base, "valid_from": "2026-01-01", "valid_to": "2025-12-31"},
    )
    assert invalid.status_code == 422, invalid.text

    assert client.post(
        "/api/v1/contracts",
        json={**base, "employee_id": 999999, "valid_from": "2010-01-01"},
    ).status_code == 404
    assert client.post(
        "/api/v1/contracts",
        json={**base, "valid_from": "2010-01-01", "agreement_id": 999999},
    ).status_code == 422


def test_v227_sac_accepts_base_salary_alias_with_examples() -> None:
    """V2-27: alias base_salary y ejemplos visibles en /docs."""
    parsed = SacInput.model_validate({
        "period": date(2026, 6, 30),
        "months_worked": Decimal("6"),
        "base_salary": Decimal("1200000"),
    })
    assert parsed.best_salary == Decimal("1200000")
    assert SacInput.model_json_schema()["examples"]
    assert VacationInput.model_json_schema()["examples"]
    assert FinalSettlementRequest.model_json_schema()["examples"]

    spec = TestClient(app).get("/openapi.json").json()
    assert spec["components"]["schemas"]["SacInput"]["examples"]


def test_v227_sac_endpoint_accepts_base_salary_alias(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """V2-27: el endpoint SAC acepta base_salary como base explícita."""
    client, _factory, _context = env
    response = client.post(
        "/api/v1/settlements/sac",
        json={"period": "2026-06-30", "months_worked": "6", "base_salary": "1200000"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "600000.00"


def test_v229_payroll_summary_groups_by_concept(env: tuple[TestClient, sessionmaker[Session], dict[str, Any]]) -> None:
    """V2-29: resumen por concepto con totales; borrador → 409."""
    client, _factory, context = env
    company_id = context["company"].id
    run_id = _create_run(client, company_id, "v229-summary")
    assert client.get(f"/api/v1/reports/payroll-summary/{run_id}").status_code == 409

    assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 200
    summary = client.get(f"/api/v1/reports/payroll-summary/{run_id}")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["employees_total"] == 2
    assert body["by_concept"]
    assert all(
        {"code", "nature", "employees", "total"} <= set(row) for row in body["by_concept"]
    )
    assert client.get("/api/v1/reports/payroll-summary/999999").status_code == 404
