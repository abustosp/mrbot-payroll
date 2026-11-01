"""Alta, edición y búsqueda de empresas desde la interfaz web (SQL real)."""

from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.database import Base
from app.database.models import Company
from app.database.session import get_db
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def token(html: str, name: str = "csrf_token") -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match
    return match.group(1)


def _tax_id(prefix: str, sequence: int) -> str:
    body = f"{prefix}{sequence:08d}"
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    remainder = 11 - sum(int(digit) * weight for digit, weight in zip(body, weights, strict=True)) % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    return f"{body}{verifier}"


def _dashed(cuit: str) -> str:
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10:]}"


def test_web_companies_create_edit_and_search(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-companies.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        seed_cuit = demo["company"].cuit
    fresh_cuit = _tax_id("30", 88888888)
    assert fresh_cuit != seed_cuit

    app = FastAPI()
    app.include_router(router)
    app.state.payroll_data_source = SqlAlchemyDataSource(factory)
    settings = Settings(web_auth_enabled=True, secret_key="test-web-companies")
    app.dependency_overrides[get_settings] = lambda: settings

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_session

    with TestClient(app) as client:
        page = client.get("/login")
        response = client.post(
            "/login",
            data={"email": "admin@example.com", "password": "admin", "csrf_token": token(page.text)},
            follow_redirects=False,
        )
        assert response.status_code == 303

        listing = client.get("/empresas")
        assert listing.status_code == 200
        assert "Proximamente" not in listing.text
        assert "Próximamente" not in listing.text
        assert "Nueva empresa" in listing.text
        assert "Dar de alta" in listing.text
        assert "CUIT" in listing.text

        csrf = token(listing.text)

        # Sin CSRF se rechaza.
        assert (
            client.post(
                "/empresas",
                data={"legal_name": "Sin Token S.A.", "cuit": fresh_cuit},
                follow_redirects=False,
            ).status_code
            == 403
        )

        # Alta válida con CUIT con guiones (se canoniza a 11 dígitos).
        created = client.post(
            "/empresas",
            data={
                "csrf_token": csrf,
                "legal_name": "Río Inventos S.A.",
                "cuit": _dashed(fresh_cuit),
                "trade_name": "Río Inventos",
                "tax_activity": "Software",
                "address": "Av. Mitre 1234, Mendoza",
                "active": "yes",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
        assert "/empresas/" in created.headers["location"]
        assert "notice=" in created.headers["location"]
        company_id = created.headers["location"].split("/empresas/")[1].split("?")[0]

        with factory() as db:
            row = db.scalar(select(Company).where(Company.cuit == fresh_cuit))
            assert row is not None
            assert row.legal_name == "Río Inventos S.A."
            assert row.trade_name == "Río Inventos"

        detail = client.get(f"/empresas/{company_id}")
        assert detail.status_code == 200
        assert "Río Inventos S.A." in detail.text
        assert "Editar empresa" in detail.text
        assert f'value="{fresh_cuit}"' in detail.text

        # CUIT inválido (dígito verificador incorrecto).
        bad_verifier = fresh_cuit[:-1] + ("0" if fresh_cuit[-1] != "0" else "1")
        invalid = client.post(
            "/empresas",
            data={"csrf_token": csrf, "legal_name": "Mala S.A.", "cuit": bad_verifier},
            follow_redirects=False,
        )
        assert invalid.status_code == 303
        assert "error=" in invalid.headers["location"]
        rejected = client.get("/empresas", params={"error": "x"})
        assert rejected.status_code == 200

        # CUIT duplicado: mensaje rioplatense específico, sin crear fila.
        with factory() as db:
            before = db.scalar(select(Company.id).where(Company.cuit == seed_cuit))
            assert before is not None
        duplicate = client.post(
            "/empresas",
            data={"csrf_token": csrf, "legal_name": "Duplicada S.A.", "cuit": _dashed(seed_cuit)},
            follow_redirects=False,
        )
        assert duplicate.status_code == 303
        assert "error=" in duplicate.headers["location"]
        assert "Ya+existe+una+empresa+con+ese+CUIT" in duplicate.headers["location"]

        # Edición válida.
        updated = client.post(
            f"/empresas/{company_id}/editar",
            data={
                "csrf_token": csrf,
                "legal_name": "Río Inventos S.R.L.",
                "cuit": fresh_cuit,
                "trade_name": "Río Inventos",
                "tax_activity": "Software y servicios",
                "address": "Av. Mitre 1234, Mendoza",
                "active": "yes",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        assert "Cambios+guardados" in updated.headers["location"]
        with factory() as db:
            row = db.get(Company, int(company_id))
            assert row is not None
            assert row.legal_name == "Río Inventos S.R.L."
            assert row.tax_activity == "Software y servicios"

        # Edición a un CUIT de otra empresa: conflicto sin pisar datos.
        clash = client.post(
            f"/empresas/{company_id}/editar",
            data={"csrf_token": csrf, "legal_name": "Río Inventos S.R.L.", "cuit": seed_cuit},
            follow_redirects=False,
        )
        assert clash.status_code == 303
        assert "Ya+existe+una+empresa+con+ese+CUIT" in clash.headers["location"]
        with factory() as db:
            assert db.get(Company, int(company_id)).cuit == fresh_cuit

        # Búsqueda: encuentra por razón social y respeta filtros vacíos.
        found = client.get("/empresas", params={"q": "inventos"})
        assert "Río Inventos S.R.L." in found.text
        missing = client.get("/empresas", params={"q": "zzzz-no-existe"})
        assert "Sin empresas" in missing.text

        partial = client.get(
            "/empresas", params={"q": "inventos"}, headers={"HX-Request": "true"}
        )
        assert partial.status_code == 200
        assert "Río Inventos S.R.L." in partial.text

    engine.dispose()
