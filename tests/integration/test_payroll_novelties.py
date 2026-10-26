from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.models import (
    Employee,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
    PayrollNovelty,
)
from app.database.session import get_db
from app.main import app
from scripts.seed_demo import seed

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


def _add_overtime_rule(session: Session, demo: dict[str, object]) -> None:
    organization = demo["organization"]
    admin = demo["admin"]
    session.add(
        PayrollConcept(
            organization_id=organization.id,
            code="HORAS_EXTRA",
            name="Horas extra",
            nature="REMUNERATIVE",
            description="Concepto de prueba para novedades.",
        )
    )
    session.flush()
    formula = FormulaDefinition(
        organization_id=organization.id,
        code="HORAS_EXTRA",
        description="Horas extra",
        current_version=1,
    )
    session.add(formula)
    session.flush()
    session.add(
        FormulaVersion(
            formula_id=formula.id,
            version=1,
            expression={
                "operator": "multiply",
                "arguments": [
                    {"variable": "NOVEDAD_HORAS_EXTRA_CANTIDAD"},
                    {"parameter": "valor_hora_extra"},
                ],
            },
            status="APPROVED",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            approved_by=admin.id,
            approved_at=datetime.now(UTC),
        )
    )
    session.add(
        NormativeParameter(
            jurisdiction="AR",
            code="valor_hora_extra",
            value=Decimal("2500"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            published_at=date(2026, 1, 1),
            version=1,
        )
    )


def _employee_by_code(session: Session, code: str) -> Employee:
    employee = session.scalar(select(Employee).where(Employee.employee_code == code))
    assert employee is not None
    return employee


def _result_for(payload: dict, employee_id: int) -> dict:
    return next(
        result for result in payload["results"] if result["employee_id"] == employee_id
    )


def test_novelty_is_used_by_overtime_concept_and_period_is_scoped(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'novelties.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        _add_overtime_rule(session, demo)
        organization = demo["organization"]
        company = demo["company"]
        employee = _employee_by_code(session, "E-001")
        session.add_all(
            [
                PayrollNovelty(
                    organization_id=organization.id,
                    employee_id=employee.id,
                    period="202606",
                    code="horas_extra",
                    kind="REMUNERATIVE",
                    quantity=Decimal("10"),
                    unit="horas",
                    amount=None,
                    description="Horas extra de junio",
                    source="test",
                    external_id="nov-june",
                ),
                PayrollNovelty(
                    organization_id=organization.id,
                    employee_id=employee.id,
                    period="202607",
                    code="horas_extra",
                    kind="REMUNERATIVE",
                    quantity=Decimal("100"),
                    unit="horas",
                    amount=None,
                    description="Horas extra de julio: no deben usarse en junio",
                    source="test",
                    external_id="nov-july",
                ),
                PayrollNovelty(
                    organization_id=organization.id,
                    employee_id=_employee_by_code(session, "E-002").id,
                    period="202606",
                    code="horas_extra",
                    kind="REMUNERATIVE",
                    quantity=Decimal("0"),
                    unit="horas",
                    amount=None,
                    description="Sin horas extra en junio",
                    source="test",
                    external_id="nov-zero",
                ),
            ]
        )
        employee_id = employee.id
        other_employee_id = _employee_by_code(session, "E-002").id
        company_id = company.id

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
                    "code": "novelties-june-2026",
                    "period_start": PERIOD_START.isoformat(),
                    "period_end": PERIOD_END.isoformat(),
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

            result = _result_for(payload, employee_id)
            overtime = next(
                item for item in result["items"] if item["code"] == "HORAS_EXTRA"
            )
            assert Decimal(overtime["amount"]) == Decimal("25000.00")

            other_result = _result_for(payload, other_employee_id)
            other_overtime = next(
                item for item in other_result["items"] if item["code"] == "HORAS_EXTRA"
            )
            assert Decimal(other_overtime["amount"]) == Decimal("0.00")

            first_hash = payload["results_hash"]

            with factory.begin() as session:
                novelty = session.scalar(
                    select(PayrollNovelty).where(
                        PayrollNovelty.external_id == "nov-june"
                    )
                )
                assert novelty is not None
                novelty.quantity = Decimal("12")

            recalculated = client.post(f"/api/v1/payroll-runs/{run_id}/calculate")
            assert recalculated.status_code == 200, recalculated.text
            recalculated_payload = recalculated.json()
            recalculated_result = _result_for(recalculated_payload, employee_id)
            recalculated_overtime = next(
                item
                for item in recalculated_result["items"]
                if item["code"] == "HORAS_EXTRA"
            )
            assert Decimal(recalculated_overtime["amount"]) == Decimal("30000.00")
            assert recalculated_payload["inputs_hash"] != payload["inputs_hash"]
            assert recalculated_payload["results_hash"] != first_hash
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
