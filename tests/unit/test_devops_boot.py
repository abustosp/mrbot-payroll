"""Chequeos minimos de arranque DevOps: B-16 (fail-fast de secreto) y B-24 (/health con base)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
from app.config import Settings
from app.main import app


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="change-me-in-production")


def test_production_rejects_empty_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="")


def test_development_allows_default_secret() -> None:
    assert Settings(environment="development").secret_key == "change-me-in-production"


def test_health_ok_with_live_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_503_when_database_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("base caida")

    monkeypatch.setattr(main_module, "engine", _BrokenEngine())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
