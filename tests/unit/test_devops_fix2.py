"""Pin minimo DevOps fix2: V2-02, V2-08, V2-11, V2-14, V2-22, PW-1/2/4/5, B-50P, B-68P, K-11."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.database import Base
from app.database.models import User

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# V2-02: el seed nunca re-escribe el admin existente.
def test_seed_never_rewrites_existing_admin(tmp_path: Path) -> None:
    from scripts.seed_demo import seed

    engine = create_engine(f"sqlite:///{tmp_path / 'seed-v2-02.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        seed(session)
    with factory.begin() as session:
        admin = session.query(User).filter_by(email="admin@example.com").one()
        from app.auth.security import hash_password

        admin.password_hash = hash_password("clave-rotada-123")
        admin.role = "editor"
    with factory.begin() as session:
        seed(session)
    with factory() as session:
        admin = session.query(User).filter_by(email="admin@example.com").one()
        from app.auth.security import verify_password

        assert verify_password("clave-rotada-123", admin.password_hash)
        assert not verify_password("admin", admin.password_hash)
    engine.dispose()


# V2-08: el entrypoint solo sella ante AlreadyExists y aborta otro fallo.
def test_entrypoint_stamps_only_on_already_exists() -> None:
    content = _read("deployment/entrypoint.sh")
    assert "lready" in content and "stamp head" in content
    assert "xists" in content
    assert "no se sello nada" in content
    assert "shortcut" not in content


# V2-11/PW-6: fuera de dev la cookie queda Secure aunque se pida False.
def test_production_forces_cookie_secure() -> None:
    from app.config import Settings

    prod = Settings(
        environment="production",
        secret_key="supersecreto-valido-1234567890",
        cookie_secure=False,
    )
    assert prod.cookie_secure is True
    dev = Settings(environment="development")
    assert dev.cookie_secure is False


# V2-14: CORS documentado junto a CSRF.
def test_cors_csrf_documented() -> None:
    example = _read(".env.example")
    assert "PAYROLL_CORS_ORIGINS" in example
    assert "X-CSRF-Token" in example
    assert "X-CSRF-Token" in _read("app/main.py")
    assert "plena confianza CSRF" in _read("docs/OPERATIONS.md")


# V2-22: checklist de restore + pg_dump en OPERATIONS.
def test_operations_restore_checklist_and_pg_dump() -> None:
    ops = _read("docs/OPERATIONS.md")
    assert "Checklist trimestral de restore" in ops
    assert "pg_dump" in ops


# PW-1: /health exige tabla real (503 sin alembic_version, 200 con ella).
def test_health_requires_real_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "pw1.sqlite"
    probe = create_engine(f"sqlite:///{db}")
    monkeypatch.setattr(main_module, "engine", probe)
    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 503
        with probe.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('head')"))
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    probe.dispose()


# PW-2/B-50P/PW-5: 500 en /api/ es JSON; en web es HTML con link relativo.
def test_500_json_on_api_and_html_on_web() -> None:
    seen: dict[str, str] = {}

    @main_module.app.get("/api/v1/_boom_fix2", include_in_schema=False)
    def _boom_api() -> None:
        raise RuntimeError("boom-api")

    @main_module.app.get("/_boom_fix2_web", include_in_schema=False)
    def _boom_web() -> None:
        raise RuntimeError("boom-web")

    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as client:
            api = client.get("/api/v1/_boom_fix2")
            assert api.status_code == 500
            assert "application/json" in api.headers["content-type"]
            assert "alembic upgrade head" in api.json()["detail"]
            seen["api_ct"] = api.headers["content-type"]
            web = client.get("/_boom_fix2_web")
            assert web.status_code == 500
            assert "text/html" in web.headers["content-type"]
            assert 'href="/salud"' in web.text
            assert "http://127.0.0.1" not in web.text
            seen["web_ct"] = web.headers["content-type"]
    finally:
        main_module.app.router.routes = [
            r for r in main_module.app.router.routes if "_boom_fix2" not in getattr(r, "path", "")
        ]
    assert seen["api_ct"].startswith("application/json")


# PW-4: 404 global HTML en web y JSON en /api/.
def test_404_global_html_web_json_api() -> None:
    with TestClient(main_module.app) as client:
        web = client.get("/esta-ruta-no-existe-xyz-fix2")
        assert web.status_code == 404
        assert "text/html" in web.headers["content-type"]
        api = client.get("/api/v1/no-existe-fix2")
        assert api.status_code == 404
        assert "application/json" in api.headers["content-type"]


# B-68P: make help existe y OPERATIONS lo cita.
def test_makefile_help_and_docs() -> None:
    content = _read("Makefile")
    assert "help:" in content
    assert "make setup" in content
    assert "make migrate" in content
    assert "make gates" in content
    assert ".PHONY" in content and "help" in content.split(".PHONY")[1].split("\n")[0]
    ops = _read("docs/OPERATIONS.md")
    assert "make setup" in ops and "make help" in ops


# K-11: docs fuera de README con cifras, health, APPROVED y cambio de clave.
def test_k11_docs_corrected() -> None:
    normative = _read("docs/NORMATIVE_DATA.md")
    assert "11 convenios, 254 documentos" in normative
    assert "786 escalas" in normative
    assert "10 convenios, 191 documentos" not in normative
    audit = _read("docs/AUDIT_2026-10-26.md")
    assert "11 CCT, 254 documentos, 786 escalas" in audit
    ops = _read("docs/OPERATIONS.md")
    assert "alembic_version" in ops and "503" in ops
    assert "change-password" in ops
    arch = _read("docs/ARCHITECTURE.md")
    assert "VALIDATED` o" not in arch
    assert "solo aprobadas" in arch
