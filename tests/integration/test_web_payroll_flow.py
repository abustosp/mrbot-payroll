from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    FormulaDefinition,
    FormulaVersion,
    Organization,
    PayrollNovelty,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.web.demo_data import DemoDataStore
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def token(html: str, name: str = "csrf_token") -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_web_payroll_flow_and_security(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-flow.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        company_id, org_id = demo["company"].id, demo["organization"].id
        basic = db.scalar(select(FormulaDefinition).where(FormulaDefinition.code == "BASICO"))
        version = db.scalar(select(FormulaVersion).where(FormulaVersion.formula_id == basic.id))
        version.expression = {"operator": "add", "arguments": [
            {"variable": "sueldo_basico"}, {"variable": "NOVEDAD_BONO_IMPORTE"},
        ]}
        db.add(User(organization_id=org_id, email="viewer@example.com", password_hash=hash_password("viewer"), role="viewer"))
        other = Organization(name="Otra", slug="other")
        db.add(other)
        db.flush()
        db.add(User(organization_id=other.id, email="other@example.com", password_hash=hash_password("other"), role="admin"))
    app = FastAPI()
    app.include_router(router)
    app.state.payroll_data_source = SqlAlchemyDataSource(factory)
    settings = Settings(web_auth_enabled=True, secret_key="test-web-payroll")
    app.dependency_overrides[get_settings] = lambda: settings

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = get_session

    with TestClient(app) as client:
        def login(email: str, password: str) -> None:
            page = client.get("/login")
            response = client.post("/login", data={"email": email, "password": password, "csrf_token": token(page.text)}, follow_redirects=False)
            assert response.status_code == 303

        login("admin@example.com", "admin")
        page = client.get("/liquidaciones")
        csrf = token(page.text)
        fields = {"company_id": str(company_id), "code": "web-junio", "period_start": "2026-06-01", "period_end": "2026-06-30", "run_type": "MONTHLY"}
        assert client.post("/liquidaciones", data=fields, follow_redirects=False).status_code == 403
        created = client.post("/liquidaciones", data={**fields, "csrf_token": csrf}, follow_redirects=False)
        assert created.status_code == 303
        with factory() as db:
            run_id = db.scalar(select(PayrollRun.id).where(PayrollRun.code == "web-junio"))
        path = f"/liquidaciones/{run_id}"
        denied = client.post(path + "/accion", data={"csrf_token": csrf, "action": "approve"}, follow_redirects=False)
        assert "error=" in denied.headers["location"]
        with factory.begin() as db:
            db.get(PayrollRun, run_id).status = "CALCULATED"
        denied = client.post(path + "/accion", data={"csrf_token": csrf, "action": "approve"}, follow_redirects=False)
        assert "error=" in denied.headers["location"]
        with factory.begin() as db:
            db.get(PayrollRun, run_id).status = "ERROR"
        denied = client.post(path + "/accion", data={"csrf_token": csrf, "action": "approve"}, follow_redirects=False)
        assert "error=" in denied.headers["location"]
        with factory.begin() as db:
            db.get(PayrollRun, run_id).status = "DRAFT"
        csv = b"Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\nE-001;202606;bono;;100;Premio\nE-002;202606;bono;;100;Premio\n"
        upload = {"file": ("novedades.csv", csv, "text/csv")}
        wrong_period = client.post(path + "/novedades", data={"csrf_token": csrf}, files={"file": ("novedades.csv", csv.replace(b"202606", b"202607"), "text/csv")}, follow_redirects=False)
        assert "202606" in wrong_period.headers["location"]
        preview = client.post(path + "/novedades", data={"csrf_token": csrf}, files=upload)
        assert preview.status_code == 200, preview.text
        assert "2 filas válidas" in preview.text
        confirmation = token(preview.text, "confirmation")
        with factory() as db:
            assert db.scalar(select(PayrollNovelty.id)) is None
        wrong = client.post(path + "/novedades", data={"csrf_token": csrf, "confirmation": confirmation}, files={"file": ("novedades.csv", csv + b"\n", "text/csv")}, follow_redirects=False)
        assert "no+coincide" in wrong.headers["location"]
        committed = client.post(path + "/novedades", data={"csrf_token": csrf, "confirmation": confirmation}, files=upload, follow_redirects=False)
        assert "2+creadas" in committed.headers["location"], committed.headers["location"]
        with factory() as db:
            assert len(db.scalars(select(PayrollNovelty)).all()) == 2
        for action in ("calculate", "reopen", "calculate", "approve"):
            result = client.post(path + "/accion", data={"csrf_token": csrf, "action": action}, follow_redirects=False)
            assert result.status_code == 303
            assert "error=" not in result.headers["location"], result.headers["location"]
            review = client.get(path)
            if action == "calculate":
                assert "Revisión y trazas" in review.text and "Fórmula" in review.text
        with factory() as db:
            assert db.get(PayrollRun, run_id).status == "APPROVED"
        assert client.get(path + "/descargar/resultados").status_code == 200
        assert client.get(path + "/descargar/f931").status_code == 200
        assert client.get("/recibos", params={"payroll_id": run_id}).status_code == 200
        client.post("/logout", data={"csrf_token": csrf})
        login("viewer@example.com", "viewer")
        viewer_csrf = token(client.get(path).text)
        assert client.post(path + "/accion", data={"csrf_token": viewer_csrf, "action": "calculate"}).status_code == 403
        client.post("/logout", data={"csrf_token": viewer_csrf})
        login("other@example.com", "other")
        other_csrf = token(client.get("/liquidaciones").text)
        assert client.get(path).status_code == 404
        assert client.post(path + "/accion", data={"csrf_token": other_csrf, "action": "calculate"}).status_code == 404
        assert client.get(path + "/descargar/resultados").status_code == 404

    app.state.payroll_data_source = DemoDataStore()
    with TestClient(app) as client:
        login_page = client.get("/login")
        client.post("/login", data={"email": settings.admin_email, "password": settings.admin_password, "csrf_token": token(login_page.text)})
        csrf = token(client.get("/liquidaciones").text)
        assert client.post("/liquidaciones", data={**fields, "csrf_token": csrf}).status_code == 403
