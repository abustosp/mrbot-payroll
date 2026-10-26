from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.service import seed_admin
from app.database import Base, models  # noqa: F401
from app.database.models import PayrollRun, User
from app.database.session import get_db
from app.main import app


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        admin = seed_admin(db, "admin@example.test", "a-long-test-password")
        organization_id = admin.organization_id
        db.add(User(organization_id=organization_id, email="viewer@example.test", password_hash=admin.password_hash, role="viewer"))
        db.commit()
    with TestClient(app) as client:
        yield client, local_session
    app.dependency_overrides.clear()
    engine.dispose()


def login(client: TestClient, email: str = "admin@example.test"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "a-long-test-password"})
    assert response.status_code == 200
    return response


def test_auth_and_company_employee_agreement_crud(api) -> None:
    client, _ = api
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/v1/companies").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": "bad"}).status_code == 401
    login_response = login(client)
    assert client.get("/api/v1/auth/me").json()["role"] == "admin"
    cookie = client.cookies.get("payroll_session")
    assert cookie
    assert "httponly" in login_response.headers["set-cookie"].lower()
    assert "samesite=lax" in login_response.headers["set-cookie"].lower()

    company = client.post(
        "/api/v1/companies",
        json={"cuit": "30711223344", "legal_name": "Empresa SA"},
    )
    assert company.status_code == 201, company.text
    company_id = company.json()["id"]
    assert client.get("/api/v1/companies?limit=1").json()["total"] == 1
    assert client.put(
        f"/api/v1/companies/{company_id}",
        json={"cuit": "30711223344", "legal_name": "Empresa SRL"},
    ).json()["legal_name"] == "Empresa SRL"

    employee = client.post(
        "/api/v1/employees",
        json={"employee_code": "E-1", "first_name": "Ana", "last_name": "Pérez", "cuil": "20301234567"},
    )
    assert employee.status_code == 201, employee.text
    assert client.get("/api/v1/employees?limit=10&offset=0").json()["items"][0]["employee_code"] == "E-1"

    concept = client.post(
        "/api/v1/concepts",
        json={"code": "BAS", "name": "Básico", "nature": "REMUNERATIVE"},
    )
    assert concept.status_code == 201, concept.text
    assert client.get("/api/v1/concepts").json()["items"][0]["code"] == "BAS"

    agreement = client.post(
        "/api/v1/agreements", json={"code": "130/75", "year": 1975, "name": "Empleados de Comercio"}
    )
    assert agreement.status_code == 201, agreement.text
    assert client.get(f"/api/v1/agreements/{agreement.json()['id']}").status_code == 200
    assert client.delete(f"/api/v1/employees/{employee.json()['id']}").status_code == 204
    assert client.delete(f"/api/v1/agreements/{agreement.json()['id']}").status_code == 204
    assert client.delete(f"/api/v1/companies/{company_id}").status_code == 204

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_formula_draft_validation_approval_payroll_and_role_guards(api) -> None:
    client, sessions = api
    login(client)
    formula = client.post(
        "/api/v1/formulas",
        json={
            "code": "BASICO",
            "description": "Sueldo básico",
            "formula": {"operator": "add", "arguments": [{"constant": "10"}, {"constant": "2.5"}]},
        },
    )
    assert formula.status_code == 201, formula.text
    formula_id = formula.json()["id"]
    assert formula.json()["status"] == "DRAFT"
    assert client.get("/api/v1/formulas").json()["total"] == 1
    assert client.post(f"/api/v1/formulas/{formula_id}/validate").json()["status"] == "VALIDATED"
    assert client.post(f"/api/v1/formulas/{formula_id}/approve").json()["status"] == "APPROVED"

    invalid = client.post("/api/v1/formulas", json={"code": "MAL", "formula": {"operator": "unknown", "arguments": []}})
    assert invalid.status_code == 201
    assert client.post(f"/api/v1/formulas/{invalid.json()['id']}/validate").status_code == 422

    company = client.post("/api/v1/companies", json={"cuit": "30799887766", "legal_name": "Otra SA"}).json()
    run = client.post(
        "/api/v1/payroll-runs",
        json={"company_id": company["id"], "code": "2026-10", "period_start": "2026-10-01", "period_end": "2026-10-31"},
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "DRAFT"
    assert client.post(f"/api/v1/payroll-runs/{run.json()['id']}/approve").status_code == 409
    with sessions() as db:
        payroll_run = db.get(PayrollRun, run.json()["id"])
        payroll_run.status = "CALCULATED"
        db.commit()
    assert client.post(f"/api/v1/payroll-runs/{run.json()['id']}/approve").json()["status"] == "APPROVED"

    viewer_response = client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "a-long-test-password"}
    )
    assert viewer_response.status_code == 200
    assert client.get("/api/v1/companies").status_code == 200
    assert client.post("/api/v1/companies", json={"cuit": "30999887766", "legal_name": "No"}).status_code == 403
    assert client.post(f"/api/v1/formulas/{formula_id}/approve").status_code == 403
