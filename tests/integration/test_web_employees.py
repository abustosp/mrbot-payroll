"""Alta y edición web de empleados punta a punta (SQL, con sesión y CSRF)."""

from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    User,
)
from app.database.session import get_db
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def _token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def _cuil(base: str) -> str:
    """Devuelve un CUIL válido con el prefijo de 10 dígitos dado."""

    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    total = sum(int(digit) * weight for digit, weight in zip(base, weights, strict=True))
    remainder = 11 - total % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    return f"{base}{verifier}"


def _app(tmp_path: Path) -> tuple[FastAPI, sessionmaker[Session]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'employees.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        db.add(User(
            organization_id=demo["organization"].id,
            email="viewer@example.com",
            password_hash=hash_password("viewer"),
            role="viewer",
        ))
    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)
    application.dependency_overrides[get_settings] = lambda: Settings(secret_key="employees-test")

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = get_session
    return application, factory


def _login(application: FastAPI, email: str, password: str) -> TestClient:
    client = TestClient(application)
    csrf = _token(client.get("/login").text)
    client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf},
    ).raise_for_status()
    return client


def test_employee_create_edit_and_search(tmp_path: Path) -> None:
    application, factory = _app(tmp_path)
    client = _login(application, "admin@example.com", "admin")
    with factory() as db:
        company = db.scalar(select(Company))
        assert company is not None
        agreement = db.scalar(select(CollectiveAgreement).where(CollectiveAgreement.code == "130/75"))
        assert agreement is not None
        categories = db.scalars(
            select(AgreementCategory).where(AgreementCategory.agreement_id == agreement.id)
        ).all()
        company_id, agreement_id = company.id, agreement.id
        category_ids = {category.code: category.id for category in categories}
    assert set(category_ids) == {"ADMIN_A", "ADMIN_B"}

    listing = client.get("/empleados")
    assert listing.status_code == 200
    assert "Próximamente" not in listing.text
    assert "Nuevo empleado" in listing.text

    form = client.get("/empleados/nuevo")
    assert form.status_code == 200
    csrf = _token(form.text)
    assert "CCT 130/75" in form.text and "Administrativo A" in form.text

    def payload(**overrides: str) -> dict[str, str]:
        data = {
            "csrf_token": csrf,
            "legajo": "L-100",
            "apellido": "Pérez",
            "nombre": "Ana",
            "cuil": _cuil("2011122233"),
            "email": "ana@example.com",
            "hire_date": "2026-03-01",
            "company_id": str(company_id),
            "agreement_id": str(agreement_id),
            "category_id": str(category_ids["ADMIN_A"]),
        }
        data.update(overrides)
        return data

    created = client.post("/empleados", data=payload(), follow_redirects=False)
    assert created.status_code == 303, created.headers.get("location")
    assert "notice=" in created.headers["location"]
    detail_url = created.headers["location"].split("?")[0]
    detail = client.get(detail_url)
    assert detail.status_code == 200 and "Ana P" in detail.text and "L-100" in detail.text

    with factory() as db:
        employee = db.scalar(select(Employee).where(Employee.employee_code == "L-100"))
        assert employee is not None and employee.first_name == "Ana"
        contract = db.scalar(
            select(EmploymentContract).where(EmploymentContract.employee_id == employee.id)
        )
        assert contract is not None and contract.company_id == company_id
        assert contract.agreement_id == agreement_id and contract.category_id == category_ids["ADMIN_A"]

    search = client.get("/empleados", params={"q": "L-100"})
    assert search.status_code == 200 and "L-100" in search.text

    bad_cuil = client.post("/empleados", data=payload(legajo="L-101", cuil="20123456780"), follow_redirects=False)
    assert "error=" in bad_cuil.headers["location"]
    with factory() as db:
        assert db.scalar(select(Employee).where(Employee.employee_code == "L-101")) is None

    no_company = client.post("/empleados", data=payload(legajo="L-102", company_id=""), follow_redirects=False)
    assert "error=" in no_company.headers["location"]
    with factory() as db:
        assert db.scalar(select(Employee).where(Employee.employee_code == "L-102")) is None

    duplicated = client.post("/empleados", data=payload(cuil=_cuil("2744455566")), follow_redirects=False)
    assert "error=" in duplicated.headers["location"]
    with factory() as db:
        assert db.scalar(select(Employee).where(Employee.cuil == _cuil("2744455566"))) is None

    employee_id = detail_url.rsplit("/", 1)[-1]
    edit_form = client.get(f"/empleados/{employee_id}/editar")
    assert edit_form.status_code == 200 and 'value="L-100"' in edit_form.text
    edit_csrf = _token(edit_form.text)

    updated = client.post(
        f"/empleados/{employee_id}",
        data={**payload(category_id=str(category_ids["ADMIN_B"])), "csrf_token": edit_csrf},
        follow_redirects=False,
    )
    assert "error=" not in updated.headers["location"], updated.headers["location"]
    with factory() as db:
        contract = db.scalar(
            select(EmploymentContract).where(EmploymentContract.employee_id == int(employee_id))
        )
        assert contract is not None and contract.category_id == category_ids["ADMIN_B"]

    mismatch = client.post(
        f"/empleados/{employee_id}",
        data={**payload(category_id="999999"), "csrf_token": edit_csrf},
        follow_redirects=False,
    )
    assert "error=" in mismatch.headers["location"]

    foreign = client.post(
        "/empleados", data=payload(legajo="L-103", company_id="999999"), follow_redirects=False
    )
    assert "error=" in foreign.headers["location"]
    with factory() as db:
        assert db.scalar(select(Employee).where(Employee.employee_code == "L-103")) is None


def test_employee_create_requires_editor_role(tmp_path: Path) -> None:
    application, _factory = _app(tmp_path)
    client = _login(application, "viewer@example.com", "viewer")
    forbidden = client.get("/empleados/nuevo")
    assert forbidden.status_code == 403
    listing = client.get("/empleados")
    assert listing.status_code == 200 and "Nuevo empleado" not in listing.text
