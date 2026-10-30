from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.ai import MetaMuseProvider, MockProvider, OpenAICompatibleProvider
from app.api.ai import AnalyzeAgreementRequest, get_ai_provider, router
from app.auth.dependencies import require_user
from app.config import Settings
from app.database.models import User
from app.database.session import get_db


def test_parse_scales_returns_validated_drafts_and_skipped_rows() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: User(id=1, organization_id=1)
    rows = [
        {"category_code": "A", "amount": "100.00", "valid_from": "2026-01-01"},
        {"category_code": "B", "amount": "200.50", "valid_from": "2026-01-01"},
        {"category_code": "C", "amount": "invalid", "valid_from": "2026-01-01"},
    ]
    with TestClient(app) as client:
        response = client.post("/ai/parse-scales", json={"document_id": "doc", "scales": rows})

    assert response.status_code == 200, response.text
    result = response.json()
    assert [p["code"] for p in result["parameters"]] == ["SUELDO_BASICO_A", "SUELDO_BASICO_B"]
    assert [p["value"] for p in result["parameters"]] == ["100.00", "200.50"]
    assert len(result["formulas"]) == 2
    for formula in result["formulas"]:
        assert formula["status"] == "draft"
        assert formula["source"]["document_id"] == "doc"
        assert formula["source"]["version"] == "1"
        assert formula["source"]["content_hash"].startswith("sha256:")
        assert formula["validation"] is not None
        assert formula["validation"]["is_valid"] is True
    assert len(result["skipped"]) == 1
    assert "row 3" in result["skipped"][0]


def test_parse_scales_limits_rows_and_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.post("/ai/parse-scales", json={"document_id": "doc", "scales": []}).status_code == 401
        app.dependency_overrides[require_user] = lambda: User(id=1, organization_id=1)
        response = client.post(
            "/ai/parse-scales", json={"document_id": "doc", "scales": [{}] * 1001}
        )
        assert response.status_code == 413


def test_provider_selection_and_missing_meta_key(monkeypatch) -> None:
    payload = AnalyzeAgreementRequest(text="text", document_id="doc")
    development = SimpleNamespace(environment="development")
    production = SimpleNamespace(environment="production")
    for name in ("PAYROLL_META_API_KEY", "PAYROLL_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("PAYROLL_AI_PROVIDER", "  META  ")
    with pytest.raises(HTTPException) as error:
        get_ai_provider(payload, development)
    assert error.value.status_code == 503
    monkeypatch.setenv("PAYROLL_META_API_KEY", "test-key")
    provider = get_ai_provider(payload, development)
    assert isinstance(provider, MetaMuseProvider)
    provider.close()

    monkeypatch.setenv("PAYROLL_AI_PROVIDER", " MOCK ")
    assert isinstance(get_ai_provider(payload, production), MockProvider)
    monkeypatch.setenv("PAYROLL_AI_PROVIDER", "unknown")
    assert isinstance(get_ai_provider(payload, development), MockProvider)
    monkeypatch.setenv("PAYROLL_AI_API_KEY", "test-key")
    provider = get_ai_provider(payload, production)
    assert isinstance(provider, OpenAICompatibleProvider)
    provider.close()


def test_provider_selection_from_settings_dotenv(monkeypatch) -> None:
    for name in (
        "PAYROLL_AI_PROVIDER",
        "PAYROLL_META_API_KEY",
        "PAYROLL_META_BASE_URL",
        "PAYROLL_META_MODEL",
        "PAYROLL_AI_API_KEY",
        "OPENAI_API_KEY",
        "MODEL_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    payload = AnalyzeAgreementRequest(text="text", document_id="doc")
    settings = Settings(ai_provider="meta", meta_api_key="settings-key")
    provider = get_ai_provider(payload, settings)
    assert isinstance(provider, MetaMuseProvider)
    assert provider.model == "muse-spark-1.3-contributor"
    provider.close()
    # El entorno del proceso mapea a Settings (precedencia sobre .env).
    monkeypatch.setenv("PAYROLL_AI_PROVIDER", "mock")
    assert Settings().ai_provider == "mock"
