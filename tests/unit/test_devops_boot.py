"""Chequeos minimos de arranque DevOps: B-16 (fail-fast de secreto) y B-24 (/health con base)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

import app.main as main_module
import scripts.seed_demo as seed_demo
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


def test_health_ok_with_live_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-24: una base migrada real responde ok (aislada en tmp, sin depender de ./data)."""
    probe = create_engine(f"sqlite:///{tmp_path / 'live.sqlite'}")
    with probe.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('head')"))
    monkeypatch.setattr(main_module, "engine", probe)
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        probe.dispose()
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_seed_help_exits_without_seeding(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        seed_demo.main(["--help"])
    assert exc.value.code == 0
    assert "usage" in capsys.readouterr().out


def test_seed_operational_error_prints_remedy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Metadata:
        @staticmethod
        def create_all(bind: object = None) -> None:
            raise OperationalError("select 1", {}, Exception("db vieja"))

    class _Base:
        metadata = _Metadata()

    monkeypatch.setattr(seed_demo, "Base", _Base())
    with pytest.raises(SystemExit) as exc:
        seed_demo.main([])
    assert exc.value.code == 1
    assert "alembic upgrade head" in capsys.readouterr().err


def test_health_reports_503_when_database_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("base caida")

    monkeypatch.setattr(main_module, "engine", _BrokenEngine())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
