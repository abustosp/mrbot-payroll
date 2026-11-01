"""Alta de convenios vía web: subida de PDF/escalas y análisis supervisado."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.database import Base
from app.database.session import get_db
from app.web.auth import WebUser, require_web_user
from app.web.demo_data import DemoDataStore
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI(title="Payroll web test")
    application.include_router(router)
    application.state.payroll_data_source = DemoDataStore()
    application.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _mini_pdf(text: str) -> bytes:
    """PDF mínimo con una línea de texto (offsets xref calculados)."""

    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    parts: list[bytes] = [b"%PDF-1.4"]
    offsets: list[int] = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(sum(len(part) + 1 for part in parts))
        parts.append(f"{number} 0 obj".encode() + b"\n" + body + b"\nendobj")
    xref_pos = sum(len(part) + 1 for part in parts)
    parts.append(f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f ".encode())
    for offset in offsets:
        parts.append(f"{offset:010d} 00000 n ".encode())
    parts.append(
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF".encode()
    )
    return b"\n".join(parts)


def test_new_page_renders_form_and_provider(client: TestClient) -> None:
    response = client.get("/propuestas-ia/nuevo")

    assert response.status_code == 200
    html = response.text
    assert "Analizar convenio" in html
    assert "convenio_file" in html
    assert "escalas_file" in html
    assert "Mock offline" in html


def test_list_links_to_analyze(client: TestClient) -> None:
    response = client.get("/propuestas-ia")

    assert response.status_code == 200
    assert "/propuestas-ia/nuevo" in response.text


def test_analyze_text_creates_demo_proposal(client: TestClient) -> None:
    response = client.post(
        "/propuestas-ia/nuevo",
        data={
            "document_id": "CCT-130-75",
            "title": "Empleados de Comercio",
            "convenio_text": "Artículo 15: adicional por antigüedad del 1% por año de servicio.",
            "escalas_text": "Administrativo A: 1200000 desde 2026-04-01.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/propuestas-ia/prop-005")
    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "Analisis mock deterministico" in detail.text


def test_analyze_txt_upload_creates_proposal(client: TestClient) -> None:
    response = client.post(
        "/propuestas-ia/nuevo",
        data={"document_id": "CCT-999-99"},
        files={"convenio_file": ("convenio.txt", b"Acuerdo salarial de prueba.", "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/propuestas-ia/prop-005")


def test_analyze_pdf_upload_creates_proposal(client: TestClient) -> None:
    pdf = _mini_pdf("Articulo 15: adicional por antiguedad del 1 por ciento.")
    response = client.post(
        "/propuestas-ia/nuevo",
        data={"document_id": "CCT-130-75"},
        files={"convenio_file": ("convenio.pdf", pdf, "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/propuestas-ia/prop-005")


def test_analyze_rejects_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/propuestas-ia/nuevo",
        data={"document_id": "CCT-130-75"},
        files={"convenio_file": ("convenio.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "Extensi" in response.text


def test_analyze_requires_content(client: TestClient) -> None:
    response = client.post(
        "/propuestas-ia/nuevo",
        data={"document_id": "CCT-130-75", "title": "Sin contenido"},
    )

    assert response.status_code == 422
    assert "sin contenido no hay an" in response.text


def test_analyze_requires_document_id(client: TestClient) -> None:
    response = client.post(
        "/propuestas-ia/nuevo",
        data={"convenio_text": "Algún texto sin identificador."},
    )

    assert response.status_code == 422
    assert "Identificador" in response.text


def test_analyze_persists_sql_proposal(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-analyze.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        admin_id = demo["admin"].id

    def _db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    application = FastAPI(title="Payroll web SQL test")
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)
    application.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[require_web_user] = lambda: WebUser(
        id=admin_id, email="admin@example.com", role="admin"
    )
    with TestClient(application) as sql_client:
        response = sql_client.post(
            "/propuestas-ia/nuevo",
            data={
                "document_id": "CCT-130-75",
                "convenio_text": "Artículo 15: adicional por antigüedad del 1% por año de servicio.",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith("/propuestas-ia/1")
        detail = sql_client.get(response.headers["location"])
        assert detail.status_code == 200
        assert "Analisis mock deterministico" in detail.text
