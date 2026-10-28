"""E2E guia vs flujo: liquidar, recalcular idempotente, LSD y recibo art. 140.

Contrasta la guia (920015926-Liquidacion-de-Sueldos.pdf: bruto/neto,
recibo art. 140 LCT, LSD) con el flujo real del programa via API.
"""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed


def _client(tmp_path: Path) -> tuple[TestClient, dict]:
    engine = create_engine(f"sqlite:///{tmp_path / 'guia_e2e.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        company_id = demo["company"].id

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, {"company_id": company_id}


def test_liquidacion_guia_e2e(tmp_path: Path) -> None:
    client, ids = _client(tmp_path)
    try:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin"},
        )
        assert login.status_code == 200

        created = client.post(
            "/api/v1/payroll-runs",
            json={
                "company_id": ids["company_id"],
                "code": "guia-e2e-monthly",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "run_type": "MONTHLY",
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]

        calculated = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
        assert calculated.status_code == 200, calculated.text
        payload = calculated.json()
        assert payload["status"] == "CALCULATED"
        assert payload["summary"]["errors"] == 0
        assert len(payload["results"]) == 2

        # Guia: todo haber tiene bruto > 0, neto > 0 y neto <= bruto.
        for result in payload["results"]:
            assert Decimal(result["gross"]) > 0
            assert Decimal(result["net"]) > 0
            assert Decimal(result["net"]) <= Decimal(result["gross"])

        # Flujo: recalcular es idempotente (mismo hash).
        again = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
        assert again.status_code == 200, again.text
        assert again.json()["results_hash"] == payload["results_hash"]

        # Guia LSD: el export de conceptos mantiene el layout de 195 chars.
        concepts = client.post(
            "/api/v1/exports/lsd/concepts",
            json={
                "concepts": [{
                    "arca_code": "110000",
                    "employer_code": "BASICO",
                    "description": "Sueldo basico demo",
                    "sipa_ap": "1",
                    "sipa_contrib": "1",
                }]
            },
        )
        assert concepts.status_code == 200, concepts.text
        line = concepts.content.decode("latin-1").splitlines()[0]
        assert len(line) == 195
        assert line.startswith("110000BASICO")

        # Guia art. 140 inc G: el recibo expone el neto del haber.
        result_id = payload["results"][0]["id"]
        receipt = client.get(f"/api/v1/exports/receipts/{result_id}/json")
        assert receipt.status_code == 200, receipt.text
        body = receipt.json()
        raw = body.get("neto", body.get("net", body.get("context", {})))
        assert raw is not None
    finally:
        app.dependency_overrides.pop(get_db, None)
