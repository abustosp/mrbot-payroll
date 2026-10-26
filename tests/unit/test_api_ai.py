from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ai import MAX_AGREEMENT_TEXT_CHARS, router
from app.auth.dependencies import require_user
from app.database.models import User
from app.database.session import get_db

ANALYSIS_PAYLOAD = {
    "text": (
        "Articulo 1: el sueldo basico se liquida por mes. "
        "Articulo 15: adicional por antiguedad del 1% por anio."
    ),
    "document_id": "cct-130-75",
    "title": "CCT 130/75",
    "version": "2026-10",
}


def _make_user(role: str = "admin", email: str | None = None) -> User:
    return User(
        id=1,
        organization_id=1,
        email=f"{role}@example.test" if email is None else email,
        password_hash="not-used-in-tests",
        role=role,
        active=True,
    )


@pytest.fixture
def ai_app() -> Iterator[FastAPI]:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[require_user] = lambda: _make_user("admin")
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(ai_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(ai_app) as test_client:
        yield test_client


def _analyze(client: TestClient, **overrides):
    payload = {**ANALYSIS_PAYLOAD, **overrides}
    return client.post("/ai/analyze-agreement", json=payload)


def _formula(client: TestClient) -> dict:
    response = _analyze(client)
    assert response.status_code == 200, response.text
    formulas = response.json()["formulas"]
    assert formulas
    return formulas[0]


def test_analyze_agreement_returns_draft_with_source_and_validation(client: TestClient) -> None:
    response = _analyze(client)

    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["document"]["document_id"] == "cct-130-75"
    assert analysis["document"]["version"] == "2026-10"
    assert analysis["document"]["title"] == "CCT 130/75"
    assert analysis["untrusted_content"] is True
    assert analysis["provider_usage"] is None
    assert analysis["formulas"]

    formula = analysis["formulas"][0]
    assert formula["status"] == "draft"
    assert formula["approved_by"] is None
    assert formula["source"]["document_id"] == "cct-130-75"
    assert formula["source"]["version"] == "2026-10"
    assert formula["source"]["content_hash"].startswith("sha256:")
    assert formula["validation"]["is_valid"] is True
    assert formula["validation"]["errors"] == []
    assert "source_traceability" in formula["validation"]["checks"]


def test_validate_proposal_returns_validation_report(client: TestClient) -> None:
    formula = _formula(client)

    response = client.post("/ai/proposals/validate", json=formula)

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["is_valid"] is True
    assert report["formula_code"] == "ANTIGUEDAD"
    assert report["errors"] == []
    assert report["validated_at"]


def test_invalid_formula_is_reported_as_invalid(client: TestClient) -> None:
    proposal = {
        "code": "MALFORMULA",
        "description": "Formula invalida",
        "formula": {"operator": "python", "arguments": []},
        "variables": [],
        "depends_on": [],
        "nature": "REMUNERATIVE",
        "source": {
            "document_id": "cct-130-75",
            "version": "2026-10",
            "page": 1,
            "article": "Articulo 99",
            "content_hash": "sha256:" + "a" * 64,
        },
        "effective_from": "2026-10-01",
    }

    response = client.post("/ai/proposals/validate", json=proposal)

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["is_valid"] is False
    assert any(issue["code"] == "unknown_operator" for issue in report["errors"])


def test_proposal_without_source_is_rejected(client: TestClient) -> None:
    proposal = {
        "code": "SIN_FUENTE",
        "formula": {
            "operator": "add",
            "arguments": [{"constant": "1"}, {"constant": "2"}],
        },
        "effective_from": "2026-10-01",
    }

    response = client.post("/ai/proposals/validate", json=proposal)

    assert response.status_code == 422
    locations = [error["loc"] for error in response.json()["detail"]]
    assert any("source" in location for location in locations)


def test_validate_reports_missing_source_hash(client: TestClient) -> None:
    proposal = {
        "code": "SIN_HASH",
        "formula": {
            "operator": "add",
            "arguments": [{"constant": "1"}, {"constant": "2"}],
        },
        "source": {
            "document_id": "cct-130-75",
            "version": "2026-10",
            "article": "Articulo 1",
        },
        "effective_from": "2026-10-01",
    }

    response = client.post("/ai/proposals/validate", json=proposal)

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["is_valid"] is False
    assert any(issue["code"] == "missing_content_hash" for issue in report["errors"])


def test_approve_without_client_approved_by_uses_authenticated_user(
    client: TestClient,
) -> None:
    formula = _formula(client)
    formula["approved_by"] = None

    response = client.post("/ai/proposals/approve", json=formula)

    assert response.status_code == 200, response.text
    assert response.json()["approved_by"] == "admin@example.test"


def test_approve_requires_admin_or_editor_role(ai_app: FastAPI, client: TestClient) -> None:
    formula = _formula(client)
    formula["approved_by"] = "otra-persona"
    ai_app.dependency_overrides[require_user] = lambda: _make_user("viewer")

    response = client.post("/ai/proposals/approve", json=formula)

    assert response.status_code == 403


def test_approve_ignores_client_supplied_identity(client: TestClient) -> None:
    formula = _formula(client)
    formula["approved_by"] = "otra-persona"

    response = client.post("/ai/proposals/approve", json=formula)

    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "admin@example.test"
    assert approved["approved_by"] != "otra-persona"
    assert approved["approved_at"]
    assert approved["source"]["content_hash"] == formula["source"]["content_hash"]
    assert approved["validation"]["is_valid"] is True

    # An approved record cannot be approved again; the route holds no state.
    assert client.post("/ai/proposals/approve", json=approved).status_code == 409


def test_approve_uses_user_id_when_email_is_missing(ai_app: FastAPI, client: TestClient) -> None:
    formula = _formula(client)
    formula["approved_by"] = "otra-persona"
    ai_app.dependency_overrides[require_user] = lambda: _make_user("admin", email="")

    response = client.post("/ai/proposals/approve", json=formula)

    assert response.status_code == 200, response.text
    assert response.json()["approved_by"] == "user:1"


def test_approve_rejects_invalid_proposal(client: TestClient) -> None:
    formula = _formula(client)
    formula["formula"] = {"operator": "python", "arguments": []}
    formula["approved_by"] = "otra-persona"

    response = client.post("/ai/proposals/approve", json=formula)

    assert response.status_code == 422
    assert "validacion deterministica" in response.json()["detail"]["message"]


def test_empty_text_is_rejected(client: TestClient) -> None:
    response = _analyze(client, text="   ")

    assert response.status_code == 422
    assert "texto" in response.json()["detail"]


def test_text_over_limit_returns_413(client: TestClient) -> None:
    response = _analyze(client, text="a" * (MAX_AGREEMENT_TEXT_CHARS + 1))

    assert response.status_code == 413
    assert str(MAX_AGREEMENT_TEXT_CHARS) in response.json()["detail"]


def test_analyze_and_approve_require_authentication() -> None:
    application = FastAPI()
    application.include_router(router)

    def _unused_session():
        yield None

    application.dependency_overrides[get_db] = _unused_session
    proposal = {
        "code": "AUTH_TEST",
        "formula": {
            "operator": "add",
            "arguments": [{"constant": "1"}, {"constant": "2"}],
        },
        "source": {
            "document_id": "doc",
            "version": "1",
            "article": "Articulo 1",
            "content_hash": "sha256:" + "a" * 64,
        },
        "effective_from": "2026-10-01",
    }
    with TestClient(application) as anonymous:
        analyze_response = anonymous.post("/ai/analyze-agreement", json=ANALYSIS_PAYLOAD)
        approve_response = anonymous.post(
            "/ai/proposals/approve",
            json={**proposal, "approved_by": "anonymous@example.test"},
        )

    assert analyze_response.status_code == 401
    assert approve_response.status_code == 401
