from __future__ import annotations

import copy
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api import settlements
from app.auth.security import sign_session
from app.auth.service import seed_admin
from app.config import get_settings
from app.database import Base
from app.database.session import get_db

SAC_PAYLOAD = {
    "period": "2026-06-30",
    "months_worked": "6",
    "remunerations": ["1000000", "1200000", "1100000"],
}

VACATION_PAYLOAD = {
    "monthly_salary": "750000",
    "days": "10",
    "days_base": "25",
    "plus_rate": "0.20",
}

FINAL_PAYLOAD: dict[str, Any] = {
    "inputs": {
        "period": "2026-06-30",
        "monthly_salary": "1200000",
        "integration_days": "15",
        "vacation_days": "10",
        "sac_months_worked": "6",
        "sac_remunerations": ["1100000", "1200000"],
        "years_of_service": "5",
        "seniority_base_salary": "1200000",
    },
    "parameters": {
        "preaviso_months": "1",
        "month_integration_days_base": "30",
        "vacation_days_base": "25",
        "vacation_plus_rate": "0.20",
        "seniority_months_per_year": "1",
    },
}


@pytest.fixture
def api_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'settlements-api.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        user_id = seed_admin(session, "admin@example.test", "a-long-test-password").id

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    application = FastAPI()
    application.include_router(settlements.router, prefix="/api/v1")
    application.dependency_overrides[get_db] = override_get_db
    settings = get_settings()
    try:
        with TestClient(application) as client:
            client.cookies.set(
                settings.session_cookie,
                sign_session(user_id, settings.secret_key),
            )
            yield client
    finally:
        application.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_sac_success_returns_decimal_strings_and_trace(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/settlements/sac", json=SAC_PAYLOAD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "2026-06-30"
    assert body["base"] == "1200000"
    assert body["months_worked"] == "6"
    assert body["days_worked"] is None
    assert body["effective_months"] == "6"
    assert body["amount"] == "600000.00"
    assert any("best_salary=1200000" in line for line in body["trace"])


def test_vacations_success_includes_plus_and_trace(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/settlements/vacations", json=VACATION_PAYLOAD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["daily_value"] == "30000"
    assert body["base_amount"] == "300000.00"
    assert body["plus_amount"] == "60000.00"
    assert body["amount"] == "360000.00"
    assert body["trace"]


def test_vacations_zero_days_returns_zero_amounts(api_client: TestClient) -> None:
    payload = {**VACATION_PAYLOAD, "days": "0"}

    response = api_client.post("/api/v1/settlements/vacations", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == "0"
    assert body["daily_value"] == "30000"
    assert body["base_amount"] == "0.00"
    assert body["plus_amount"] == "0.00"
    assert body["amount"] == "0.00"


def test_final_settlement_success_returns_items_totals_and_trace(
    api_client: TestClient,
) -> None:
    response = api_client.post("/api/v1/settlements/final", json=FINAL_PAYLOAD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "2026-06-30"
    assert [item["code"] for item in body["items"]] == [
        "PREAVISO",
        "INTEGRACION_MES",
        "VACACIONES_NO_GOZADAS",
        "SAC_PROPORCIONAL",
        "INDEMNIZACION_ANTIGUEDAD",
    ]
    by_code = {item["code"]: item for item in body["items"]}
    assert by_code["PREAVISO"]["amount"] == "1200000.00"
    assert by_code["INTEGRACION_MES"]["amount"] == "600000.00"
    assert by_code["VACACIONES_NO_GOZADAS"]["amount"] == "576000.00"
    assert by_code["SAC_PROPORCIONAL"]["amount"] == "600000.00"
    assert by_code["INDEMNIZACION_ANTIGUEDAD"]["amount"] == "6000000.00"
    assert by_code["INDEMNIZACION_ANTIGUEDAD"]["nature"] == "NON_REMUNERATIVE"
    assert all(isinstance(item["amount"], str) for item in body["items"])
    assert body["total"] == "8976000.00"
    assert body["remunerative_total"] == "2976000.00"
    assert body["non_remunerative_total"] == "6000000.00"
    assert any("final settlement period=2026-06-30" in line for line in body["trace"])


def test_final_settlement_missing_parameter_returns_422_with_detail(
    api_client: TestClient,
) -> None:
    payload = copy.deepcopy(FINAL_PAYLOAD)
    del payload["parameters"]["vacation_plus_rate"]

    response = api_client.post("/api/v1/settlements/final", json=payload)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "vacation_plus_rate" for error in detail)


def test_final_settlement_sac_days_without_base_returns_422_with_detail(
    api_client: TestClient,
) -> None:
    payload = copy.deepcopy(FINAL_PAYLOAD)
    payload["inputs"]["sac_days_worked"] = "15"

    response = api_client.post("/api/v1/settlements/final", json=payload)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "sac_days_base" in detail


def test_invalid_period_returns_422_with_detail(api_client: TestClient) -> None:
    payload = {**SAC_PAYLOAD, "period": "2026-02-30"}

    response = api_client.post("/api/v1/settlements/sac", json=payload)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "period" for error in detail)


def test_endpoints_require_authentication(api_client: TestClient) -> None:
    api_client.cookies.clear()

    responses = [
        api_client.post("/api/v1/settlements/sac", json=SAC_PAYLOAD),
        api_client.post("/api/v1/settlements/vacations", json=VACATION_PAYLOAD),
        api_client.post("/api/v1/settlements/final", json=FINAL_PAYLOAD),
    ]

    for response in responses:
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Autenticación requerida"


def test_vacations_without_plus_rate_warns(api_client: TestClient) -> None:
    """B-29: omitted plus_rate liquidates zero plus with a warning."""

    payload = {key: value for key, value in VACATION_PAYLOAD.items() if key != "plus_rate"}

    response = api_client.post("/api/v1/settlements/vacations", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plus_rate"] == "0"
    assert body["plus_amount"] == "0.00"
    assert any("plus_rate" in warning for warning in body["warnings"])


def test_sac_with_seven_remunerations_is_rejected(api_client: TestClient) -> None:
    """B-28: a seven-pay window inflates the SAC and is rejected."""

    payload = {**SAC_PAYLOAD, "remunerations": ["1000000"] * 7}

    response = api_client.post("/api/v1/settlements/sac", json=payload)

    assert response.status_code == 422, response.text
    assert "at most 6" in response.json()["detail"]
