from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.web.demo_data import DemoDataStore
from app.web.routes import TEMPLATES_DIR, router, templates


def _template_files() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def test_jinja_environment_autoescapes_html() -> None:
    assert callable(templates.env.autoescape)
    assert templates.env.autoescape("dashboard.html") is True
    assert templates.env.autoescape("receipt.html") is True


def test_all_templates_compile() -> None:
    names = templates.env.list_templates()
    assert "base.html" in names
    assert "dashboard.html" in names
    assert "companies/list.html" in names
    assert "receipts/detail.html" in names

    for name in names:
        if name.endswith(".html"):
            templates.env.get_template(name)


def test_templates_do_not_mark_dynamic_data_safe() -> None:
    files = _template_files()
    assert files

    offenders = [
        str(path.relative_to(TEMPLATES_DIR))
        for path in files
        if "|safe" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_base_template_uses_local_assets_before_cdn_enhancements() -> None:
    content = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")

    assert "url_for('web_css')" in content
    assert "url_for('web_js')" in content
    assert "admin-lte" in content
    assert "htmx.org" in content
    assert content.index("admin-lte") < content.index("url_for('web_css')")
    assert 'lang="es"' in content
    assert "sidebar" in content
    assert "aria-label" in content


def test_templates_use_empty_states_and_error_view() -> None:
    empty = (TEMPLATES_DIR / "partials" / "_empty_state.html").read_text(encoding="utf-8")
    not_found = (TEMPLATES_DIR / "not_found.html").read_text(encoding="utf-8")

    assert "empty-state" in empty
    assert "Sin resultados" in empty
    assert "404" in not_found
    assert "Volver al dashboard" in not_found


def test_templates_do_not_contain_secret_placeholders() -> None:
    files = _template_files()
    forbidden = ["secret_key", "admin_password", "PAYROLL_SECRET", "change-me-in-production"]

    for path in files:
        content = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in content, f"{needle} encontrado en {path}"


def test_receipt_filter_refreshes_zip_scope() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.payroll_data_source = DemoDataStore()
    app.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    with TestClient(app) as client:
        response = client.get(
            "/recibos",
            params={"company_id": "cmp-andes", "period": "2026-09", "payroll_id": "pay-2026-09"},
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "company_id=cmp-andes&amp;period=2026-09&amp;payroll_id=pay-2026-09" in response.text
    assert "incluida la búsqueda y el estado" in response.text


@pytest.mark.parametrize(
    "relative",
    [
        "companies/_table.html",
        "companies/detail.html",
        "employees/detail.html",
    ],
)
def test_demo_copy_only_renders_in_demo_mode(relative: str) -> None:
    """B-52: ningún literal demo incondicional en plantillas compartidas."""

    content = (TEMPLATES_DIR / relative).read_text(encoding="utf-8")
    assert "{% if demo_mode %}" in content
    for line in content.splitlines():
        if "demostra" in line.lower():
            assert "demo_mode" in line, f"literal demo sin guarda en {relative}: {line.strip()}"
