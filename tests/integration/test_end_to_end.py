from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.models import Employee, PayrollItem, PayrollResult, PayrollTrace
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed


def test_seed_login_calculate_recalculate_and_export(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        company_id = demo["company"].id
        employer_cuit = demo["company"].cuit

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin"},
            )
            assert login.status_code == 200

            created = client.post(
                "/api/v1/payroll-runs",
                json={
                    "company_id": company_id,
                    "code": "demo-june-2026",
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
            assert payload["summary"]["calculated"] == 2
            assert payload["summary"]["errors"] == 0
            assert len(payload["results"]) == 2
            assert all(
                Decimal(item["gross"]) > 0 and Decimal(item["net"]) > 0
                for item in payload["results"]
            )
            first_hash = payload["results_hash"]

            recalculated = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
            assert recalculated.status_code == 200, recalculated.text
            assert recalculated.json()["results_hash"] == first_hash

            with factory() as session:
                assert session.scalar(select(func.count()).select_from(PayrollResult)) == 2
                assert session.scalar(select(func.count()).select_from(PayrollItem)) == 6
                assert session.scalar(select(func.count()).select_from(PayrollTrace).where(PayrollTrace.employee_id.is_not(None))) == 2
                review = session.scalar(select(PayrollTrace).where(PayrollTrace.event == "CALCULATION_REVIEW"))
                assert review is not None and review.detail["summary"]["calculated"] == 2
                employees = {
                    employee.id: employee
                    for employee in session.scalars(select(Employee)).all()
                }

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
            assert concepts.headers["content-type"].startswith("text/plain")
            assert "charset=latin-1" in concepts.headers["content-type"]
            concept_line = concepts.content.decode("latin-1").splitlines()[0]
            assert len(concept_line) == 195
            assert concept_line.startswith("110000BASICO    ")

            workers = []
            for result in payload["results"]:
                employee = employees[result["employee_id"]]
                workers.append({
                    "cuil": employee.cuil,
                    "items": [
                        {
                            "concept_code": item["code"],
                            "amount": (
                                f"-{item['amount']}"
                                if item["nature"] == "DEDUCTION"
                                else item["amount"]
                            ),
                        }
                        for item in result["items"]
                    ],
                })
            liquidation = client.post(
                "/api/v1/exports/lsd/liquidations",
                json={
                    "employer_cuit": employer_cuit,
                    "period": "202606",
                    "workers": workers,
                },
            )
            assert liquidation.status_code == 200, liquidation.text
            assert liquidation.content.decode("latin-1").startswith("01")

            receipt = client.post(f"/api/v1/exports/receipts/{payload['results'][0]['id']}")
            assert receipt.status_code == 200, receipt.text
            assert receipt.headers["content-type"] == "application/pdf"
            assert receipt.content.startswith(b"%PDF-")

            report = client.get(f"/api/v1/reports/f931/{run_id}.xlsx")
            assert report.status_code == 200, report.text
            assert report.content.startswith(b"PK")
            approved = client.post(f"/api/v1/payroll-runs/{run_id}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "APPROVED"
            for action in ("calculate", "approve", "reopen"):
                blocked = client.post(f"/api/v1/payroll-runs/{run_id}/{action}")
                assert blocked.status_code == 409, (action, blocked.text)
            after = client.get(f"/api/v1/payroll-runs/{run_id}")
            assert after.json()["status"] == "APPROVED"
            with factory() as session:
                assert session.scalar(select(func.count()).select_from(PayrollResult)) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
