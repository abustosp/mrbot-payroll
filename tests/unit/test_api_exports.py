from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed


def test_lsd_exports_require_auth_and_report_invalid_payloads(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'exports-api.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        seed(session)

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            route = "/api/v1/exports/lsd/concepts"
            assert client.post(route, json={"concepts": []}).status_code == 401

            client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            ).raise_for_status()
            invalid = client.post(
                "/api/v1/exports/lsd/liquidations",
                json={
                    "employer_cuit": "00000000000",
                    "period": "202613",
                    "workers": [{"cuil": "00000000000", "items": []}],
                },
            )
            assert invalid.status_code == 422
            assert "Liquidación LSD inválida" in invalid.json()["detail"]

            concepts = client.post(
                route,
                json={"concepts": [{"arca_code": "001", "employer_code": "BASICO", "description": "Basico"}]},
            )
            assert concepts.status_code == 200, concepts.text
            assert concepts.headers["content-type"].startswith("text/plain")
            assert concepts.content.decode("latin-1").isascii()
            # B-82: la descarga avisa que no tiene validez ante ARCA.
            assert "sin-validez-arca" in concepts.headers["content-disposition"]

            liquidation = client.post(
                "/api/v1/exports/lsd/liquidations",
                json={
                    "employer_cuit": "30-12345678-1",
                    "period": "202601",
                    "liquidation_number": 1,
                    "workers": [
                        {
                            "cuil": "20-12345678-6",
                            "legajo": "A1",
                            "pay_date": "2026-01-31",
                            "rubric_date": "2026-01-31",
                            "items": [{"concept_code": "BASICO", "quantity": 1, "amount": "100000.00"}],
                            "record04": {},
                        }
                    ],
                },
            )
            assert liquidation.status_code == 200, liquidation.text
            assert "sin-validez-arca" in liquidation.headers["content-disposition"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_lsd_descriptions_document_version_and_example() -> None:
    # B-46/B-88: /docs muestra ejemplo de payload y version del layout.
    from app.api.exports import router
    from app.exporters.txt.lsd import LAYOUT_VERSION

    descriptions = {
        route.path: route.description
        for route in router.routes
        if "/lsd/" in getattr(route, "path", "")
    }

    assert set(descriptions) == {
        "/exports/lsd/liquidations",
        "/exports/lsd/concepts",
    }
    for path, description in descriptions.items():
        assert LAYOUT_VERSION in description, path
        assert "ARCA" in description, path
    assert "employer_cuit" in descriptions["/exports/lsd/liquidations"]
    assert "arca_code" in descriptions["/exports/lsd/concepts"]
