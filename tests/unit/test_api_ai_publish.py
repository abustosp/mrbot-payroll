from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.auth.service import seed_admin
from app.config import get_settings
from app.database import Base, models  # noqa: F401
from app.database.models import (
    AiProposal,
    AuditLog,
    FormulaDefinition,
    FormulaVersion,
    User,
)
from app.database.session import get_db
from app.main import app
from app.web.auth import CSRF_COOKIE
from app.web.sql_data_source import SqlAlchemyDataSource

PASSWORD = "a-long-test-password"
ANALYSIS_PAYLOAD = {
    "text": (
        "Articulo 1: el sueldo basico se liquida por mes. "
        "Articulo 15: adicional por antiguedad del 1% por anio."
    ),
    "document_id": "cct-130-75",
    "title": "CCT 130/75",
    "version": "2026-10",
}


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session], int], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ai-proposals.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        admin = seed_admin(db, "admin@example.test", PASSWORD)
        admin_id = admin.id
        db.add(
            User(
                organization_id=admin.organization_id,
                email="viewer@example.test",
                password_hash=admin.password_hash,
                role="viewer",
            )
        )
        db.commit()
    with TestClient(app) as client:
        yield client, local_session, admin_id
    app.dependency_overrides.clear()
    engine.dispose()


def login(client: TestClient, email: str = "admin@example.test") -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def analyze(client: TestClient) -> dict:
    response = client.post("/api/v1/ai/analyze-agreement", json=ANALYSIS_PAYLOAD)
    assert response.status_code == 200, response.text
    return response.json()


def persist(client: TestClient, analysis: dict | None = None):
    return client.post("/api/v1/ai/proposals", json=analysis or analyze(client))


def test_web_approval_uses_api_validation_and_keeps_published_final(
    api: tuple[TestClient, sessionmaker[Session], int], monkeypatch,
) -> None:
    client, sessions, admin_id = api
    login(client)
    proposal_id = persist(client).json()["id"]
    monkeypatch.setattr(app.state, "payroll_data_source", SqlAlchemyDataSource(sessions), raising=False)
    page = client.get(f"/propuestas-ia/{proposal_id}")
    assert page.status_code == 200
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    approved = client.post(
        f"/propuestas-ia/{proposal_id}/estado",
        data={"status": "approved", "csrf_token": token}, follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    with sessions() as db:
        row = db.get(AiProposal, proposal_id)
        assert row.status == "approved"
        assert row.approved_by == admin_id
        assert row.approved_at is not None
    assert client.post(f"/api/v1/ai/proposals/{proposal_id}/publish").status_code == 200
    reopened = client.post(
        f"/propuestas-ia/{proposal_id}/estado",
        data={"status": "in_review", "csrf_token": token},
    )
    assert reopened.status_code == 409
    with sessions() as db:
        assert db.get(AiProposal, proposal_id).status == "published"


def test_persist_approve_and_publish_creates_only_draft(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, admin_id = api
    login(client)

    created = persist(client)
    assert created.status_code == 201, created.text
    proposal = created.json()
    proposal_id = proposal["id"]
    assert proposal["status"] == "draft"
    assert proposal["document_id"] == "cct-130-75"
    assert proposal["document_hash"].startswith("sha256:")
    assert proposal["validation_json"]["is_valid"] is True
    assert proposal["approved_by"] is None
    assert proposal["published_formula_id"] is None
    with sessions() as db:
        assert db.scalar(select(FormulaDefinition)) is None
        assert db.scalar(select(FormulaVersion)) is None

    approved = client.post(f"/api/v1/ai/proposals/{proposal_id}/approve")
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["approved_by"] == admin_id
    assert approved_body["approved_at"] is not None
    assert approved_body["published_formula_id"] is None
    with sessions() as db:
        assert db.scalar(select(FormulaDefinition)) is None

    published = client.post(f"/api/v1/ai/proposals/{proposal_id}/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "published"
    assert body["formula_status"] == "DRAFT"
    assert body["published_formula_id"] == body["formula_id"]
    formula_version_id = body["formula_version_id"]

    with sessions() as db:
        proposal_row = db.get(AiProposal, proposal_id)
        assert proposal_row.status == "published"
        assert proposal_row.published_formula_id == body["formula_id"]
        definitions = db.scalars(select(FormulaDefinition)).all()
        assert len(definitions) == 1
        assert definitions[0].code == "ANTIGUEDAD"
        versions = db.scalars(select(FormulaVersion)).all()
        assert len(versions) == 1
        assert versions[0].id == formula_version_id
        assert versions[0].status == "DRAFT"
        assert versions[0].version == 1
        assert versions[0].approved_by is None
        assert versions[0].approved_at is None
        audits = db.scalars(
            select(AuditLog).where(AuditLog.action == "ai_proposal.published")
        ).all()
        assert len(audits) == 1
        assert audits[0].entity_id == str(proposal_id)

    listed = client.get("/api/v1/formulas").json()["items"]
    assert [(item["code"], item["version"], item["status"]) for item in listed] == [
        ("ANTIGUEDAD", 1, "DRAFT")
    ]


def test_persist_accepts_wrapped_analysis(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, _ = api
    login(client)

    response = client.post("/api/v1/ai/proposals", json={"analysis": analyze(client)})

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"
    with sessions() as db:
        assert db.scalar(select(AiProposal)) is not None


def test_publish_requires_approved_proposal(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, _, _ = api
    login(client)
    proposal_id = persist(client).json()["id"]

    response = client.post(f"/api/v1/ai/proposals/{proposal_id}/publish")

    assert response.status_code == 409
    assert "aprobada" in response.json()["detail"].lower()


def test_viewer_cannot_publish(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, _ = api
    login(client)
    proposal_id = persist(client).json()["id"]
    assert client.post(f"/api/v1/ai/proposals/{proposal_id}/approve").status_code == 200
    login(client, "viewer@example.test")

    response = client.post(f"/api/v1/ai/proposals/{proposal_id}/publish")

    assert response.status_code == 403
    with sessions() as db:
        assert db.get(AiProposal, proposal_id).status == "approved"
        assert db.scalar(select(FormulaDefinition)) is None


def test_publish_does_not_reuse_existing_formula_with_same_code(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, _ = api
    login(client)
    existing = client.post(
        "/api/v1/formulas",
        json={
            "code": "ANTIGUEDAD",
            "description": "Formula existente",
            "formula": {"operator": "add", "arguments": [{"constant": "1"}, {"constant": "2"}]},
            "valid_from": "2025-01-01",
            "valid_to": "2025-12-31",
        },
    )
    assert existing.status_code == 201, existing.text
    proposal_id = persist(client).json()["id"]
    assert client.post(f"/api/v1/ai/proposals/{proposal_id}/approve").status_code == 200

    response = client.post(f"/api/v1/ai/proposals/{proposal_id}/publish")

    assert response.status_code == 409
    assert "antiguedad" in response.json()["detail"].lower()
    with sessions() as db:
        definitions = db.scalars(select(FormulaDefinition)).all()
        assert len(definitions) == 1
        assert definitions[0].id == existing.json()["id"]
        assert db.get(AiProposal, proposal_id).status == "approved"


def test_invalid_analysis_is_not_persisted(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, _ = api
    login(client)
    analysis = analyze(client)
    analysis["formulas"][0]["formula"] = {"operator": "python", "arguments": []}

    response = persist(client, analysis)

    assert response.status_code == 422
    with sessions() as db:
        assert db.scalar(select(AiProposal)) is None


def test_unvalidated_draft_cannot_be_approved(
    api: tuple[TestClient, sessionmaker[Session], int],
) -> None:
    client, sessions, admin_id = api
    login(client)
    with sessions() as db:
        row = AiProposal(
            organization_id=db.get(User, admin_id).organization_id,
            document_id="manual",
            raw_json=analyze(client),
            validation_json=None,
            status="draft",
        )
        db.add(row)
        db.commit()
        proposal_id = row.id

    response = client.post(f"/api/v1/ai/proposals/{proposal_id}/approve")

    assert response.status_code == 409
    assert "validación" in response.json()["detail"].lower()


def test_migration_has_one_head_and_creates_ai_proposals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    get_settings.cache_clear()
    database_path = tmp_path / "migrations.db"
    monkeypatch.setenv("PAYROLL_DATABASE_URL", f"sqlite:///{database_path}")
    try:
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("script_location", str(project_root / "alembic"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert len(heads) == 1

        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert "ai_proposals" in tables
        assert "payroll_novelties" in tables
    finally:
        get_settings.cache_clear()
