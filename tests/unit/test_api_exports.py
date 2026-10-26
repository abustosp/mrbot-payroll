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
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
