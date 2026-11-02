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
from app.database.models import Employee, EmploymentContract
from app.database.session import get_db
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed

CSV = (
    "Legajo;Apellido;Nombre;CUIL;Fecha de ingreso;Categoría;Convenio;Email\n"
    "E-901;López;Pedro;20-23456789-7;20/05/2024;ADMIN_A;CCT 130/75;pedro@example.com\n"
).encode()


def _token(html: str, name: str = "csrf_token") -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_web_employee_import_preview_then_confirm(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'emp-import.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        company_id = seed(db)["company"].id
    app = FastAPI()
    app.include_router(router)
    app.state.payroll_data_source = SqlAlchemyDataSource(factory)
    app.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=True, secret_key="test-emp-import")

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = get_session

    with TestClient(app) as client:
        login = client.post("/login", data={"email": "admin@example.com", "password": "admin",
                                            "csrf_token": _token(client.get("/login").text)}, follow_redirects=False)
        assert login.status_code == 303
        page = client.get("/empleados/importar")
        assert page.status_code == 200 and "Revisar archivo" in page.text
        csrf = _token(page.text)
        files = {"file": ("empleados.csv", CSV, "text/csv")}
        data = {"csrf_token": csrf, "company_id": str(company_id)}

        preview = client.post("/empleados/importar", data=data, files=files)
        assert preview.status_code == 200 and "E-901" in preview.text and "Confirmar importación" in preview.text
        with factory() as db:  # la vista previa no crea nada
            assert db.scalar(select(Employee).where(Employee.employee_code == "E-901")) is None

        confirmed = client.post("/empleados/importar", data={**data, "confirmation": _token(preview.text, "confirmation")},
                                files={"file": ("empleados.csv", CSV, "text/csv")}, follow_redirects=False)
        assert confirmed.status_code == 303 and "notice=" in confirmed.headers["location"], confirmed.headers["location"]
        with factory() as db:
            employee = db.scalar(select(Employee).where(Employee.employee_code == "E-901"))
            contract = db.scalar(select(EmploymentContract).where(EmploymentContract.employee_id == employee.id))
            assert contract.company_id == company_id and contract.category_id is not None
    engine.dispose()
