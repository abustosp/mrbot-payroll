"""Fix2 API: B-47P (200+errors[]), B-82P (headers LSD), V2-10 (demo PDF/JSON)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.exports import router as exports_router
from app.api.imports import router as imports_router
from app.auth.dependencies import require_user
from app.database import Base
from app.database.models import (
    Company,
    Employee,
    Organization,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.exporters.pdf.receipts import DEMO_SEAL


def _client(tmp_path: Path, router, prefix: str) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'fix2.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id=1, name="Org", slug="org"))
    application = FastAPI()
    application.include_router(router, prefix=prefix)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    admin = User(
        id=1,
        organization_id=1,
        email="admin@example.test",
        password_hash="x",
        role="admin",
        active=True,
    )
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_user] = lambda: admin
    with TestClient(application) as client:
        yield client, factory  # type: ignore[misc]
    application.dependency_overrides.clear()
    engine.dispose()


def test_b47p_preview_es_200_con_errors_y_cuil_11_digitos(tmp_path: Path) -> None:
    for client, _ in _client(tmp_path, imports_router, "/api/v1"):
        content = (
            "Legajo;Apellido;Nombre;CUIL;Fecha de ingreso\n"
            "1;Pérez;Juan;20-12345678-7;15/03/2024\n"
        ).encode()
        response = client.post(
            "/api/v1/imports/employees",
            files={"file": ("employees.csv", content, "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["error_count"] == 1
        assert data["errors"][0]["code"] == "cuil_invalido"
        assert "11" in data["errors"][0]["message"]


def test_b47p_xss_rechazado_en_api(tmp_path: Path) -> None:
    for client, _ in _client(tmp_path, imports_router, "/api/v1"):
        content = (
            b"Legajo;Apellido;Nombre;CUIL;Fecha de ingreso\n"
            b"1;<script>;Juan;20-12345678-6;15/03/2024\n"
        )
        response = client.post(
            "/api/v1/imports/employees",
            files={"file": ("employees.csv", content, "text/csv")},
        )
        assert response.status_code == 200, response.text
        assert any(
            e["code"] == "caracteres_no_permitidos" for e in response.json()["errors"]
        )


def test_b82p_lsd_descarga_lleva_marca_sin_validez(tmp_path: Path) -> None:
    for client, _ in _client(tmp_path, exports_router, "/api/v1"):
        response = client.post(
            "/api/v1/exports/lsd/concepts",
            json={
                "concepts": [
                    {
                        "arca_code": "001",
                        "employer_code": "BASICO",
                        "description": "Basico",
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert "sin-validez-arca" in response.headers["content-disposition"]
        assert (
            response.headers["X-Sin-Validez-ARCA"] == "borrador-sin-validez-arca"
        )


def _seed_receipt(factory: sessionmaker[Session]) -> int:
    with factory.begin() as session:
        company = Company(
            organization_id=1, cuit="30712345678", legal_name="Empresa SA"
        )
        session.add(company)
        session.flush()
        employee = Employee(
            organization_id=1,
            employee_code="E-1",
            first_name="Juan",
            last_name="Perez",
            cuil="20123456786",
            hire_date=date(2024, 1, 1),
        )
        session.add(employee)
        session.flush()
        run = PayrollRun(
            organization_id=1,
            company_id=company.id,
            code="LIQ-2026-06",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="CALCULATED",
            created_by=1,
        )
        session.add(run)
        session.flush()
        result = PayrollResult(
            payroll_run_id=run.id,
            employee_id=employee.id,
            remunerative=Decimal("100"),
            non_remunerative=Decimal("0"),
            deductions=Decimal("0"),
            contributions=Decimal("0"),
            gross=Decimal("100"),
            net=Decimal("100"),
            employer_cost=Decimal("100"),
        )
        session.add(result)
        session.flush()
        session.add(
            PayrollItem(
                payroll_result_id=result.id,
                code="BASICO",
                description="Basico",
                nature="REMUNERATIVE",
                quantity=Decimal("1"),
                amount=Decimal("100"),
            )
        )
        session.flush()
        return result.id


def test_v2_10_recibo_demo_pdf_y_json_llevan_sello(tmp_path: Path) -> None:
    for client, factory in _client(tmp_path, exports_router, "/api/v1"):
        result_id = _seed_receipt(factory)

        pdf_demo = client.post(f"/api/v1/exports/receipts/{result_id}?demo=true")
        assert pdf_demo.status_code == 200, pdf_demo.text
        assert "demo-sin-validez" in pdf_demo.headers["content-disposition"]
        assert "DEMO" in pdf_demo.headers["X-Recibo-Demo"]
        assert pdf_demo.content.startswith(b"%PDF")

        pdf_normal = client.post(f"/api/v1/exports/receipts/{result_id}")
        assert pdf_normal.status_code == 200, pdf_normal.text
        assert "demo-sin-validez" not in pdf_normal.headers["content-disposition"]
        assert "X-Recibo-Demo" not in pdf_normal.headers

        json_demo = client.get(f"/api/v1/exports/receipts/{result_id}/json?demo=true")
        assert json_demo.status_code == 200, json_demo.text
        payload = json_demo.json()
        assert payload["is_demo"] is True
        assert payload["demo_seal"] == DEMO_SEAL
        assert payload["demo_note"] != ""

        json_normal = client.get(f"/api/v1/exports/receipts/{result_id}/json")
        assert json_normal.status_code == 200, json_normal.text
        assert json_normal.json()["is_demo"] is False
