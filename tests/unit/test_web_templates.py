from __future__ import annotations

from pathlib import Path

import pytest

from app.web.routes import TEMPLATES_DIR, templates


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
