"""Pins de los fixes de documentación web (B-54/B-69/B-72/K-11/B-24).

Evidencian que el README principal y ``app/web/README.md`` describen el
comportamiento real del código en vez de los bugs ya corregidos.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_readme_cites_real_normative_figures() -> None:
    """K-11: 11 CCT, 254 documentos y 786 escalas verificadas."""

    readme = _read("README.md")
    assert "11 CCT, 254 documentos y 786 escalas verificadas (778 desde 2020 y 8 históricas)" in readme
    assert "786 escalas\nverificadas" in readme
    assert "10 CCT, 191 documentos" not in readme
    assert "235 escalas" not in readme


def test_readme_describes_health_checks_truthfully() -> None:
    """B-24/K-11: /health con 503 y /salud con prueba real en modo SQL."""

    readme = _read("README.md")
    assert "503 si la base no responde" in readme
    assert "prueba `alembic_version`" in readme
    assert "no comprueba la base de datos" not in readme
    assert "tabla `users` legible" in readme
    assert "El health visual no\ncomprueba la base" not in readme


def test_readme_documents_change_password_and_sql_isolation() -> None:
    """K-11: change-password existe; SQL filtra por organización."""

    readme = _read("README.md")
    assert "POST /api/v1/auth/change-password" in readme
    assert "rota `session_version`" in readme
    assert "no existe un endpoint para cambiar" not in readme
    assert "sin separación por organización" not in readme
    assert "cualquier usuario autenticado\npuede ver la proyección completa" not in readme
    assert "filtra por la organización del usuario autenticado" in readme


def test_readme_cites_coverage_gate_and_safe_env_copy() -> None:
    """B-69/B-72: cobertura citada y `cp .env` no destructivo."""

    readme = _read("README.md")
    assert "--cov=app --cov-fail-under=80" in readme
    assert "80 %" in readme
    assert readme.count("[ -f .env ] || cp .env.example .env") == 2


def test_readme_proposal_tray_covers_both_modes() -> None:
    """B-54: la bandeja y las acciones valen para demo y SQL."""

    readme = _read("README.md")
    assert "Bandeja de revisión (demo y SQL)" in readme
    assert "funcionan en\nambos modos (demo y SQL)" in readme
    assert "solo funcionan en el" not in readme


def test_web_readme_matches_sql_behavior() -> None:
    """B-54/K-11: app/web/README sin claims demo-only ni helpers muertos."""

    web_readme = _read("app/web/README.md")
    assert "Bandeja de revisión (demo y SQL)" in web_readme
    assert "funcionan en ambos modos (demo y SQL)" in web_readme
    assert "solo se ejecutan en el store demo" not in web_readme
    assert "read_session_payload" in web_readme
    assert "`read_session`" not in web_readme
    assert "rota\n`session_version`" in web_readme
