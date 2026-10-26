from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings, get_settings
from app.web.demo_data import DemoDataStore
from app.web.routes import router


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI(title="Payroll web test")
    application.include_router(router)
    application.state.payroll_data_source = DemoDataStore()
    # Las pruebas existentes de presentación no son de autenticación; se
    # desactiva la sesión con un override explícito. La autenticación real se
    # cubre en tests/unit/test_web_auth.py.
    application.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_renders_shell_and_metrics(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Payroll Argentina" in html
    assert "Dashboard" in html
    assert "Empresas" in html
    assert "Empleados activos" in html
    assert "Andes Logística S.A." in html
    assert "Septiembre 2026" in html
    assert "Modo demo" in html
    assert "/static/app.css" in html
    assert "app-sidebar" in html
    assert "page-actions" in html


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/empresas", "Cartera de empresas"),
        ("/empresas/cmp-andes", "Datos del empleador"),
        ("/empleados", "Legajos"),
        ("/empleados/emp-001", "Datos del legajo"),
        ("/convenios", "Convenios"),
        ("/convenios/cct-130-75", "Categorías profesionales"),
        ("/liquidaciones", "Historial de liquidaciones"),
        ("/liquidaciones/pay-2026-09", "Resultados por empleado"),
        ("/propuestas-ia", "Bandeja de revisión"),
        ("/propuestas-ia/prop-001", "Reglas propuestas"),
        ("/recibos", "Recibos de sueldo"),
        ("/recibos/rec-2026-09-001", "Vista previa del recibo"),
        ("/salud", "Componentes"),
    ],
)
def test_main_pages_render(client: TestClient, path: str, expected: str) -> None:
    response = client.get(path)

    assert response.status_code == 200, path
    assert expected in response.text
    assert "<html" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/empresas/inexistente",
        "/empleados/inexistente",
        "/convenios/inexistente",
        "/liquidaciones/inexistente",
        "/propuestas-ia/inexistente",
        "/recibos/inexistente",
    ],
)
def test_unknown_entities_render_visual_404(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "404" in response.text
    assert "Volver al dashboard" in response.text
    assert "<html" in response.text


def test_companies_filter_and_htmx_partial(client: TestClient) -> None:
    full = client.get("/empresas")
    assert "Andes Logística S.A." in full.text
    assert "Pampa Alimentos S.R.L." in full.text

    filtered = client.get("/empresas", params={"q": "andes"})
    assert filtered.status_code == 200
    assert "Andes Logística S.A." in filtered.text
    assert "Pampa Alimentos S.R.L." not in filtered.text

    partial = client.get(
        "/empresas",
        params={"q": "andes"},
        headers={"HX-Request": "true"},
    )
    assert partial.status_code == 200
    assert "<html" not in partial.text
    assert partial.text.lstrip().startswith('<div id="companies-results">')
    assert "Andes Logística S.A." in partial.text
    assert "filter-summary" in partial.text

    empty = client.get("/empresas", params={"q": "zzzz-no-existe"})
    assert empty.status_code == 200
    assert "Sin empresas" in empty.text
    assert "Limpiar búsqueda" in empty.text


def test_employees_filters_and_htmx_partial(client: TestClient) -> None:
    response = client.get(
        "/empleados",
        params={"company_id": "cmp-pampa", "status": "active"},
    )

    assert response.status_code == 200
    assert "Ana Paula Medina" in response.text
    assert "Santiago Ríos" in response.text
    assert "Carla Ortiz" not in response.text

    all_staff = client.get("/empleados")
    assert "Carla Ortiz" in all_staff.text

    partial = client.get(
        "/empleados",
        params={"company_id": "cmp-andes"},
        headers={"HX-Request": "true"},
    )
    assert partial.status_code == 200
    assert "<html" not in partial.text
    assert partial.text.lstrip().startswith('<div id="employees-results">')


def test_payroll_filters_and_htmx_partial(client: TestClient) -> None:
    review = client.get("/liquidaciones", params={"status": "review"})
    assert review.status_code == 200
    assert "Septiembre 2026" in review.text
    assert "Octubre 2026" not in review.text

    partial = client.get(
        "/liquidaciones",
        params={"status": "review"},
        headers={"HX-Request": "true"},
    )
    assert partial.status_code == 200
    assert "<html" not in partial.text
    assert partial.text.lstrip().startswith('<div id="payrolls-results">')


def test_proposal_status_actions(client: TestClient) -> None:
    redirect = client.post(
        "/propuestas-ia/prop-001/estado",
        data={"status": "approved"},
        follow_redirects=False,
    )
    assert redirect.status_code == 303
    assert "propuestas-ia/prop-001" in redirect.headers["location"]
    assert "updated=1" in redirect.headers["location"]

    detail = client.get("/propuestas-ia/prop-001?updated=1")
    assert detail.status_code == 200
    assert "Aprobada" in detail.text
    assert "se actualizó correctamente" in detail.text

    partial = client.post(
        "/propuestas-ia/prop-001/estado",
        data={"status": "rejected"},
        headers={"HX-Request": "true"},
    )
    assert partial.status_code == 200
    assert "proposal-status-panel" in partial.text
    assert "Rechazada" in partial.text
    assert "<html" not in partial.text

    rejected = client.get("/propuestas-ia/prop-001")
    assert "Rechazada" in rejected.text

    invalid = client.post("/propuestas-ia/prop-001/estado", data={"status": "invented"})
    assert invalid.status_code == 400

    missing = client.post("/propuestas-ia/inexistente/estado", data={"status": "approved"})
    assert missing.status_code == 404

    missing_htmx = client.post(
        "/propuestas-ia/inexistente/estado",
        data={"status": "approved"},
        headers={"HX-Request": "true"},
    )
    assert missing_htmx.status_code == 404
    assert "no encontrada" in missing_htmx.text.lower()


def test_receipt_preview_and_pdf(client: TestClient) -> None:
    preview = client.get("/recibos/rec-2026-09-001/vista")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    assert "Recibo de Sueldo" in preview.text
    assert "María Fernanda Gómez" in preview.text
    assert "Neto a cobrar" in preview.text
    assert "R-2026-09-0001" in preview.text
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert preview.headers["cache-control"] == "private, no-store"
    assert "default-src 'none'" in preview.headers["content-security-policy"]

    pdf = client.get("/recibos/rec-2026-09-001/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]
    assert "R-2026-09-0001" in pdf.headers["content-disposition"]

    reader = PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "María Fernanda Gómez" in text
    assert "Neto a cobrar" in text
    assert "Septiembre 2026" in text


def test_receipts_zip(client: TestClient) -> None:
    response = client.get("/recibos/lote.zip", params={"period": "2026-09"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == 3
        assert all(name.endswith(".pdf") for name in names)
        assert "R-2026-09-0001.pdf" in names

        first_pdf = archive.read("R-2026-09-0001.pdf")
        assert first_pdf.startswith(b"%PDF")
        reader = PdfReader(io.BytesIO(first_pdf))
        assert len(reader.pages) >= 1
        assert "María Fernanda Gómez" in (reader.pages[0].extract_text() or "")

    missing = client.get("/recibos/lote.zip", params={"period": "1999-01"})
    assert missing.status_code == 404


def test_personal_data_is_escaped_in_web_and_receipt(client: TestClient, app: FastAPI) -> None:
    store: DemoDataStore = app.state.payroll_data_source
    store.companies[0].name = '<script>alert("empresa")</script>'
    receipt = store.get_receipt("rec-2026-09-001")
    assert receipt is not None
    receipt.employee["name"] = '<script>alert("persona")</script>'

    listing = client.get("/empresas")
    assert listing.status_code == 200
    assert "<script>alert" not in listing.text
    assert "&lt;script&gt;" in listing.text

    detail = client.get("/recibos/rec-2026-09-001")
    assert detail.status_code == 200
    assert "<script>alert" not in detail.text
    assert "&lt;script&gt;" in detail.text

    preview = client.get("/recibos/rec-2026-09-001/vista")
    assert preview.status_code == 200
    assert "<script>alert" not in preview.text
    assert "&lt;script&gt;" in preview.text

    pdf = client.get("/recibos/rec-2026-09-001/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_static_assets_are_served_locally(client: TestClient) -> None:
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert ".app-sidebar" in css.text
    assert ".data-table" in css.text
    assert ".badge--success" in css.text
    assert ".empty-state" in css.text
    assert "@import" not in css.text
    assert "http://" not in css.text
    assert "https://" not in css.text

    javascript = client.get("/static/app.js")
    assert javascript.status_code == 200
    assert "sidebar-open" in javascript.text


def test_health_page_reports_components(client: TestClient) -> None:
    response = client.get("/salud")

    assert response.status_code == 200
    assert "Estado del sistema" in response.text
    assert "Aplicación web" in response.text
    assert "Plantillas" in response.text
    assert "Exportador PDF" in response.text
    assert "WeasyPrint" in response.text
    assert "Datos demo en memoria" in response.text
    assert "app.state.payroll_data_source" in response.text
    assert "Sistema operativo" in response.text

    alias = client.get("/health/visual")
    assert alias.status_code == 200
    assert "Estado del sistema" in alias.text


def test_router_can_be_mounted_with_prefix() -> None:
    application = FastAPI()
    application.include_router(router, prefix="/panel")
    application.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    with TestClient(application) as test_client:
        response = test_client.get("/panel/")
        assert response.status_code == 200
        assert "/panel/empresas" in response.text
        assert "/panel/static/app.css" in response.text

        detail = test_client.get("/panel/recibos/rec-2026-09-001")
        assert detail.status_code == 200
        assert "/panel/recibos/rec-2026-09-001/vista" in detail.text
        assert "/panel/recibos/rec-2026-09-001/pdf" in detail.text


def test_list_pages_expose_htmx_filters(client: TestClient) -> None:
    for path, target in [
        ("/empresas", "#companies-results"),
        ("/empleados", "#employees-results"),
        ("/liquidaciones", "#payrolls-results"),
        ("/propuestas-ia", "#proposals-results"),
        ("/recibos", "#receipts-results"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert 'hx-get="' in response.text
        assert f'hx-target="{target}"' in response.text
