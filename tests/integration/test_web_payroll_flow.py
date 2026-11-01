from __future__ import annotations

import re
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    AgreementCategory,
    FormulaDefinition,
    FormulaVersion,
    Organization,
    PayrollNovelty,
    PayrollRun,
    SalaryScale,
    User,
)
from app.database.session import get_db
from app.main import app as full_app
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


def _tax_id(prefix: str, sequence: int) -> str:
    """CUIT/CUIL con dígito verificador válido (mismo algoritmo que el seed)."""

    body = f"{prefix}{sequence:08d}"
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    remainder = 11 - sum(int(digit) * weight for digit, weight in zip(body, weights, strict=True)) % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    return f"{body}{verifier}"


def test_transversal_e2e_empresa_a_exportacion(tmp_path: Path) -> None:
    """Punta a punta: empresa -> empleado -> convenio -> análisis IA ->
    propuesta -> aprobación -> liquidación -> exportación (LSD/F931/recibo).

    Usa SQLite temporal y TestClient sobre la app completa. Falla si alguna
    página del circuito muestra un marcador de contenido pendiente.
    """

    engine = create_engine(f"sqlite:///{tmp_path / 'transversal.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        seed(db)

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    full_app.dependency_overrides[get_db] = get_session
    had_source = hasattr(full_app.state, "payroll_data_source")
    previous_source = getattr(full_app.state, "payroll_data_source", None)
    full_app.state.payroll_data_source = SqlAlchemyDataSource(factory)
    try:
        with TestClient(full_app) as client:
            # 0. Login web; la misma cookie de sesión vale para API y web.
            login_page = client.get("/login")
            assert login_page.status_code == 200
            web_csrf = token(login_page.text)
            logged = client.post(
                "/login",
                data={"email": "admin@example.com", "password": "admin", "csrf_token": web_csrf},
                follow_redirects=False,
            )
            assert logged.status_code == 303

            # 1. Crear empresa.
            company = client.post("/api/v1/companies", json={
                "cuit": _tax_id("30", 79999999),
                "legal_name": "Transversal S.R.L.",
                "trade_name": "Transversal",
                "tax_activity": "Servicios",
                "address": "Calle Falsa 123",
            })
            assert company.status_code == 201, company.text
            company_id = company.json()["id"]

            # 2. Cargar empleado.
            employee = client.post("/api/v1/employees", json={
                "employee_code": "E2E-001",
                "first_name": "Juana",
                "last_name": "Pérez",
                "cuil": _tax_id("27", 40123456),
                "hire_date": "2024-03-01",
            })
            assert employee.status_code == 201, employee.text
            employee_id = employee.json()["id"]

            # 3. Cargar convenio (API) y vincular al empleado (base del cálculo).
            # La web lista los convenios globales con contrato en la
            # organización, así que el contrato usa el convenio recién creado.
            # La categoría/escala se siembra como el seed: todavía no hay
            # endpoint público de categorías, igual que la carga inicial.
            agreement = client.post("/api/v1/agreements", json={
                "code": "CCT-E2E-1", "year": 2026, "name": "Convenio E2E de prueba",
            })
            assert agreement.status_code == 201, agreement.text
            agreement_id = agreement.json()["id"]
            with factory.begin() as db:
                category = AgreementCategory(
                    agreement_id=agreement_id,
                    code="E2E-ADM",
                    name="Administración E2E",
                )
                db.add(category)
                db.flush()
                db.add(SalaryScale(
                    category_id=category.id,
                    valid_from=date(2024, 1, 1),
                    valid_to=None,
                    base_salary=Decimal("1500000"),
                    additional=Decimal("0"),
                ))
                category_id = category.id
            contract = client.post("/api/v1/contracts", json={
                "employee_id": employee_id,
                "company_id": company_id,
                "agreement_id": agreement_id,
                "category_id": category_id,
                "valid_from": "2024-03-01",
                "employment_type": "full_time",
                "weekly_hours": 48,
                "monthly_salary": "1500000",
            })
            assert contract.status_code == 201, contract.text

            # Las altas ya son visibles en la web de consulta, sin pendientes.
            for path, marker in (
                ("/empresas", "Transversal"),
                ("/empleados", "Juana"),
                ("/convenios", "CCT-E2E-1"),
            ):
                page = client.get(path)
                assert page.status_code == 200, path
                assert "ximamente" not in page.text, path
                assert "coming soon" not in page.text.lower(), path
                assert marker in page.text, path

            # 4. Análisis IA del convenio (texto pegado; mock offline en dev).
            form = client.get("/propuestas-ia/nuevo")
            assert form.status_code == 200
            web_csrf = token(form.text)
            analysis = client.post("/propuestas-ia/nuevo", data={
                "document_id": "CCT-E2E-1",
                "title": "Convenio E2E de prueba",
                "convenio_text": "Artículo 15: adicional por antigüedad del 1% por año de servicio.",
                "escalas_text": "Administrativo A: 1500000 desde 2026-06-01.",
                "csrf_token": web_csrf,
            }, follow_redirects=False)
            assert analysis.status_code == 303, analysis.text
            proposal_url = analysis.headers["location"]
            detail = client.get(proposal_url)
            assert detail.status_code == 200
            assert "Analisis mock deterministico" in detail.text

            # 5. Aprobar la propuesta (revisión humana).
            proposal_id = proposal_url.rstrip("/").rsplit("/", 1)[-1]
            approved = client.post(
                f"/propuestas-ia/{proposal_id}/estado",
                data={"status": "approved", "csrf_token": web_csrf},
                follow_redirects=False,
            )
            assert approved.status_code == 303, approved.text
            assert client.get(proposal_url).status_code == 200

            # 6. Liquidar: crear, calcular y aprobar la empresa nueva.
            web_csrf = token(client.get("/liquidaciones").text)
            created = client.post("/liquidaciones", data={
                "company_id": str(company_id),
                "code": "e2e-transversal",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "run_type": "MONTHLY",
                "csrf_token": web_csrf,
            }, follow_redirects=False)
            assert created.status_code == 303, created.text
            with factory() as db:
                run_id = db.scalar(select(PayrollRun.id).where(PayrollRun.code == "e2e-transversal"))
            assert run_id is not None
            run_path = f"/liquidaciones/{run_id}"
            for action in ("calculate", "approve"):
                result = client.post(
                    run_path + "/accion",
                    data={"csrf_token": web_csrf, "action": action},
                    follow_redirects=False,
                )
                assert result.status_code == 303, (action, result.text)
                assert "error=" not in result.headers["location"], (action, result.headers["location"])
            with factory() as db:
                assert db.get(PayrollRun, run_id).status == "APPROVED"

            # 7. Exportar: resultados, F931, LSD y recibo del empleado nuevo.
            assert client.get(run_path + "/descargar/resultados").status_code == 200
            assert client.get(run_path + "/descargar/f931").status_code == 200
            lsd = client.post("/api/v1/exports/lsd/concepts", json={"concepts": [{
                "arca_code": "110000",
                "employer_code": "BASICO",
                "description": "Sueldo basico e2e",
                "sipa_ap": "1",
                "sipa_contrib": "1",
            }]})
            assert lsd.status_code == 200, lsd.text
            assert len(lsd.content.decode("latin-1").splitlines()[0]) == 195
            receipts_page = client.get("/recibos", params={"payroll_id": run_id})
            assert receipts_page.status_code == 200
            assert "Juana" in receipts_page.text
            match = re.search(r"/recibos/(\d+)", receipts_page.text)
            assert match, "la liquidación aprobada debe exponer el recibo del empleado"
            receipt_id = f"/recibos/{match.group(1)}"
            assert client.get(receipt_id).status_code == 200
            assert client.get(receipt_id + "/vista").status_code == 200
            pdf = client.get(receipt_id + "/pdf", follow_redirects=False)
            assert pdf.status_code in (200, 303), pdf.status_code
            if pdf.status_code == 200:
                assert pdf.content[:4] == b"%PDF"
    finally:
        full_app.dependency_overrides.pop(get_db, None)
        if had_source:
            full_app.state.payroll_data_source = previous_source
        else:
            del full_app.state.payroll_data_source
