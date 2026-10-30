"""Must fixes B-09/B-14/B-15: un test enfocado por item."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import FastAPI, status
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.providers import MockProvider, OpenAICompatibleProvider
from app.ai.schemas import AgreementAnalysis
from app.ai.validation import validate_formula_proposal
from app.api.ai import AnalyzeAgreementRequest, _mock_analysis_json, get_ai_provider
from app.api.ai import router as ai_router
from app.auth.dependencies import require_user
from app.auth.security import login_attempts
from app.auth.service import seed_admin
from app.config import Settings, get_settings
from app.database import Base, models  # noqa: F401
from app.database.models import User
from app.database.session import get_db
from app.main import app

PASSWORD = "a-long-test-password"


def test_b09_validation_with_context_rejects_unknown_parameter() -> None:
    """Barrera con contexto: el flujo persistido valida con el analisis."""

    analysis = AgreementAnalysis.model_validate(
        {
            "document": {
                "document_id": "d1",
                "version": "1",
                "content_hash": "sha256:" + "0" * 64,
            },
            "summary": "analisis de prueba para la barrera B-09",
            "formulas": [
                {
                    "code": "X",
                    "description": "d",
                    "formula": {
                        "operator": "add",
                        "arguments": [
                            {"parameter": "NOEXISTE"},
                            {"constant": "1"},
                        ],
                    },
                    "variables": [],
                    "depends_on": [],
                    "source": {
                        "document_id": "d1",
                        "version": "1",
                        "content_hash": "sha256:" + "0" * 64,
                    },
                    "effective_from": "2026-01-01",
                    "tests": [],
                }
            ],
            "analyzed_at": "2026-10-26T12:00:00+00:00",
        }
    )
    report = validate_formula_proposal(analysis.formulas[0], analysis=analysis)
    assert report.is_valid is False
    assert any(issue.code == "unknown_parameter" for issue in report.errors)


def test_b09_persisted_proposal_with_unknown_parameter_is_rejected(api) -> None:
    """Una propuesta stateless aprobada con NOEXISTE no se puede persistir."""

    client, _ = api
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.test", "password": PASSWORD},
        ).status_code
        == 200
    )
    analysis = client.post(
        "/api/v1/ai/analyze-agreement",
        json={"text": "Articulo 1: texto de prueba.", "document_id": "d1"},
    )
    assert analysis.status_code == 200, analysis.text
    bad = analysis.json()
    bad["formulas"][0]["formula"] = {
        "operator": "add",
        "arguments": [{"parameter": "NOEXISTE"}, {"constant": "1"}],
    }
    persisted = client.post("/api/v1/ai/proposals", json=bad)
    assert persisted.status_code == 422, persisted.text
    detail = persisted.json()["detail"]
    assert "determin" in detail["message"]
    assert any(
        issue["code"] == "unknown_parameter" for issue in detail["errors"]
    )


def _provider_payload() -> AnalyzeAgreementRequest:
    return AnalyzeAgreementRequest(text="t", document_id="d1")


def test_b14_mock_only_in_dev_and_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYROLL_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = _provider_payload()
    assert isinstance(
        get_ai_provider(payload, Settings(environment="development")), MockProvider
    )
    assert isinstance(
        get_ai_provider(
            payload, Settings(environment="test", secret_key="test-secret-1234")
        ),
        MockProvider,
    )


def test_b14_production_without_key_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYROLL_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        get_ai_provider(
            _provider_payload(),
            Settings(environment="production", secret_key="test-secret-1234"),
        )
    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_b14_production_with_key_returns_real_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYROLL_AI_API_KEY", "test-key")
    provider = get_ai_provider(
        _provider_payload(),
        Settings(environment="production", secret_key="test-secret-1234"),
    )
    assert isinstance(provider, OpenAICompatibleProvider)


def test_b14_analyze_without_key_outside_dev_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYROLL_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    application = FastAPI()
    application.include_router(ai_router)
    application.dependency_overrides[require_user] = lambda: User(
        id=1,
        organization_id=1,
        email="admin@example.test",
        password_hash="x",
        role="admin",
        active=True,
    )
    application.dependency_overrides[get_settings] = lambda: Settings(
        environment="production", secret_key="test-secret-1234"
    )
    with TestClient(application) as client:
        response = client.post(
            "/ai/analyze-agreement",
            json={"text": "hola mundo", "document_id": "d1"},
        )
    application.dependency_overrides.clear()
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.text


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'apiauth-must.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db

    def override_ai_provider(payload: AnalyzeAgreementRequest) -> MockProvider:
        # Estos tests ejercitan barreras de auth/persistencia, no la seleccion
        # de proveedor: el mock deterministico aisla del .env local y la red.
        return MockProvider(_mock_analysis_json(payload.to_metadata()))

    app.dependency_overrides[get_ai_provider] = override_ai_provider
    with local_session() as db:
        seed_admin(db, "admin@example.test", PASSWORD)
    login_attempts.clear()
    with TestClient(app) as client:
        yield client, local_session
    login_attempts.clear()
    app.dependency_overrides.clear()
    engine.dispose()


def test_v203_login_rejects_unbounded_password_before_hashing(api) -> None:
    """V2-03: password gigante da 422 sin llegar a PBKDF2; el login normal sigue 200."""

    from pydantic import ValidationError

    from app.api.schemas import LoginInput

    client, _ = api
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.test", "password": PASSWORD},
        ).status_code
        == 200
    )
    oversized = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.test", "password": "x" * 300},
    )
    assert oversized.status_code == 422, oversized.text
    with pytest.raises(ValidationError):
        LoginInput.model_validate({"email": "a@b.c", "password": "x" * 1000000})


def test_b15_logout_requires_auth_and_invalidates_old_token(api) -> None:
    client, sessions = api
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.test", "password": PASSWORD},
        ).status_code
        == 200
    )
    old_cookie = client.cookies.get("payroll_session")
    assert old_cookie
    with sessions() as db:
        before = db.scalar(select(User).where(User.email == "admin@example.test"))
        assert before is not None
        assert before.session_version == 1

    assert client.post("/api/v1/auth/logout").status_code == 204
    with sessions() as db:
        after = db.scalar(select(User).where(User.email == "admin@example.test"))
        assert after is not None
        assert after.session_version == 2

    client.cookies.set("payroll_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401

    client.cookies.clear()
    assert client.post("/api/v1/auth/logout").status_code == 401
