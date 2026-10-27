from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.service import seed_admin
from app.database import Base, models  # noqa: F401
from app.database.models import FormulaVersion
from app.database.session import get_db
from app.main import app

PASSWORD = "a-long-test-password"
VALID_FORMULA = {
    "operator": "add",
    "arguments": [{"constant": "10"}, {"constant": "2.5"}],
}
INVALID_FORMULA = {"operator": "not_a_real_operator", "arguments": []}


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'apiauth-should-fixes.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        seed_admin(db, "admin@example.test", PASSWORD)
    with TestClient(app) as client:
        yield client, local_session
    app.dependency_overrides.clear()
    engine.dispose()


def login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.test", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def test_b42_referenced_concept_delete_is_409_and_keeps_formula(api) -> None:
    # V2-20: solo las fórmulas APPROVED bloquean; se aprueba antes del 409.
    client, local_session = api
    login(client)
    concept = client.post(
        "/api/v1/concepts",
        json={"code": "BAS", "name": "Básico", "nature": "REMUNERATIVE"},
    )
    assert concept.status_code == 201, concept.text
    formula = client.post(
        "/api/v1/formulas",
        json={"code": "REFBAS", "formula": {"concept": "BAS"}},
    )
    assert formula.status_code == 201, formula.text
    with local_session.begin() as db:
        version = db.scalar(
            select(FormulaVersion).where(
                FormulaVersion.formula_id == formula.json()["id"]
            )
        )
        assert version is not None
        version.status = "APPROVED"

    response = client.delete(f"/api/v1/concepts/{concept.json()['id']}")

    assert response.status_code == 409, response.text
    assert "BAS" in response.text
    assert client.get(f"/api/v1/concepts/{concept.json()['id']}").status_code == 200
    assert client.get("/api/v1/formulas").json()["total"] == 1


def test_b42_unreferenced_concept_delete_is_204(api) -> None:
    client, _ = api
    login(client)
    concept = client.post(
        "/api/v1/concepts",
        json={"code": "LIBRE", "name": "Libre", "nature": "REMUNERATIVE"},
    )
    assert concept.status_code == 201, concept.text

    assert client.delete(f"/api/v1/concepts/{concept.json()['id']}").status_code == 204


def test_b74_invalid_email_is_rejected(api) -> None:
    client, _ = api
    login(client)

    response = client.post(
        "/api/v1/employees",
        json={
            "employee_code": "E-1",
            "first_name": "Ana",
            "last_name": "Pérez",
            "email": "no-es-email",
        },
    )

    assert response.status_code == 422, response.text


def test_b74_valid_email_is_accepted_trimmed(api) -> None:
    client, _ = api
    login(client)

    response = client.post(
        "/api/v1/employees",
        json={
            "employee_code": "E-2",
            "first_name": "Ana",
            "last_name": "Pérez",
            "email": "  ana@example.com  ",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["email"] == "ana@example.com"


def test_b81_invalid_dsl_returns_draft_with_warnings(api) -> None:
    client, _ = api
    login(client)

    response = client.post(
        "/api/v1/formulas",
        json={"code": "MALA", "formula": INVALID_FORMULA},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "DRAFT"
    assert payload["warnings"] != []
    assert (
        client.post(f"/api/v1/formulas/{payload['id']}/validate").status_code == 422
    )


def test_b81_valid_dsl_returns_no_warnings(api) -> None:
    client, _ = api
    login(client)

    response = client.post(
        "/api/v1/formulas",
        json={"code": "BUENA", "formula": VALID_FORMULA},
    )

    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []


def test_v228_404_carries_resource_id(api) -> None:
    """V2-28: el 404 genérico incluye el id pedido."""

    client, _ = api
    login(client)

    response = client.get("/api/v1/companies/9999")

    assert response.status_code == 404, response.text
    assert "9999" in response.json()["detail"]


def test_v228_409_carries_id_and_state(api) -> None:
    """V2-28: los 409 de transición incluyen id y estado actual."""

    client, _ = api
    login(client)

    formula = client.post(
        "/api/v1/formulas",
        json={"code": "ESTADO", "formula": VALID_FORMULA},
    )
    assert formula.status_code == 201, formula.text
    formula_id = formula.json()["id"]
    assert client.post(f"/api/v1/formulas/{formula_id}/validate").status_code == 200
    assert client.post(f"/api/v1/formulas/{formula_id}/approve").status_code == 200
    retry = client.post(f"/api/v1/formulas/{formula_id}/validate")
    assert retry.status_code == 409, retry.text
    assert str(formula_id) in retry.json()["detail"]
    assert "APPROVED" in retry.json()["detail"]

    company = client.post(
        "/api/v1/companies", json={"cuit": "30799887769", "legal_name": "Estado SA"}
    ).json()
    run = client.post(
        "/api/v1/payroll-runs",
        json={
            "company_id": company["id"],
            "code": "2026-10",
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
        },
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    approval = client.post(f"/api/v1/payroll-runs/{run_id}/approve")
    assert approval.status_code == 409, approval.text
    assert str(run_id) in approval.json()["detail"]
    assert "DRAFT" in approval.json()["detail"]


def test_v228_lsd_internal_error_is_spanish_with_detail() -> None:
    """V2-28: el error interno LSD habla ES y conserva el detalle (kind)."""

    import pytest

    from app.exporters.txt.lsd import FieldSpec

    with pytest.raises(ValueError, match="no soportado"):
        FieldSpec(name="f", width=1, kind="nope")
    try:
        FieldSpec(name="f", width=1, kind="nope")
    except ValueError as exc:
        assert "nope" in str(exc)
