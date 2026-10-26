from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password, sign_session
from app.config import get_settings
from app.database import Base
from app.database.models import PayrollResult, PayrollRun, User
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed


def test_calculation_requires_editor_and_rejects_approved_runs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll-api.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        company_id = demo["company"].id
        viewer = User(
            organization_id=demo["organization"].id,
            email="viewer@example.com",
            password_hash=hash_password("viewer"),
            role="viewer",
        )
        session.add(viewer)
        session.flush()
        viewer_id = viewer.id

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            ).raise_for_status()
            created = client.post(
                "/api/v1/payroll-runs",
                json={
                    "company_id": company_id,
                    "code": "permission-check",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                },
            )
            created.raise_for_status()
            run_id = created.json()["id"]

            client.cookies.set(
                get_settings().session_cookie,
                sign_session(viewer_id, get_settings().secret_key),
            )
            assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 403

            client.cookies.clear()
            client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            ).raise_for_status()
            assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 200
            client.post(f"/api/v1/payroll-runs/{run_id}/approve").raise_for_status()
            rejected = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
            assert rejected.status_code == 409
            assert "aprobada o cerrada" in rejected.json()["detail"]

            with factory() as session:
                assert session.get(PayrollRun, run_id).status == "APPROVED"

            # B-10: un run_type especial no se crea ni se calcula como mensual.
            special = client.post(
                "/api/v1/payroll-runs",
                json={
                    "company_id": company_id,
                    "code": "sac-mistaken",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                    "run_type": "SAC",
                },
            )
            assert special.status_code == 422, special.text
            assert "run_type" in special.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_calculate_paginates_detail_but_keeps_full_summary(tmp_path: Path) -> None:
    # B-36: el resumen siempre cubre a todos; el detalle se pagina.
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll-paged.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        company_id = demo["company"].id

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            ).raise_for_status()
            run_id = client.post(
                "/api/v1/payroll-runs",
                json={
                    "company_id": company_id,
                    "code": "paged-run",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-30",
                },
            ).json()["id"]

            full = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
            assert full.status_code == 200, full.text
            full_body = full.json()
            assert full_body["summary"]["calculated"] == 2
            assert full_body["results_total"] == 2

            page = client.post(
                f"/api/v1/payroll-runs/{run_id}/calculate",
                params={"results_limit": 1, "results_offset": 1},
            )
            assert page.status_code == 200, page.text
            page_body = page.json()
            assert len(page_body["results"]) == 1
            assert page_body["results_total"] == 2
            assert page_body["summary"] == full_body["summary"]
            assert page_body["results_hash"] == full_body["results_hash"]

            with factory() as session:
                assert session.scalar(select(func.count()).select_from(PayrollResult)) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
