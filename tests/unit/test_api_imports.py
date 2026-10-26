from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.imports import MAX_IMPORT_BYTES, router
from app.auth.dependencies import require_user
from app.database import Base
from app.database.models import (
    Company,
    Employee,
    EmploymentContract,
    Organization,
    PayrollNovelty,
    User,
)
from app.database.session import get_db
from app.importers import cuil_check_digit

EMPLOYEE_HEADERS = [
    "Legajo",
    "Apellido",
    "Nombre",
    "CUIL",
    "Fecha de ingreso",
    "Categoría",
    "Convenio",
    "Email",
]
NOVELTY_HEADERS = ["Legajo", "Periodo", "Tipo", "Cantidad", "Importe"]


def make_cuil(base: str) -> str:
    return base + str(cuil_check_digit(base))


def employee_csv(rows: list[str]) -> bytes:
    return ("\n".join([";".join(EMPLOYEE_HEADERS), *rows]) + "\n").encode("utf-8")


def novelty_csv(rows: list[str]) -> bytes:
    return ("\n".join([";".join(NOVELTY_HEADERS), *rows]) + "\n").encode("utf-8")


def make_xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def add_employee(
    factory: sessionmaker[Session],
    employee_code: str,
    *,
    organization_id: int = 1,
    first_name: str = "Test",
    last_name: str = "Empleado",
) -> int:
    with factory.begin() as session:
        employee = Employee(
            organization_id=organization_id,
            employee_code=employee_code,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(employee)
        session.flush()
        return employee.id


@pytest.fixture
def api(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker[Session], FastAPI], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'imports-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id=1, name="Organizacion Test", slug="test"))

    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    admin = User(
        id=1,
        organization_id=1,
        email="admin@example.test",
        password_hash="not-used-in-tests",
        role="admin",
        active=True,
    )
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_user] = lambda: admin
    with TestClient(application) as client:
        yield client, factory, application
    application.dependency_overrides.clear()
    engine.dispose()


def _post_employee_file(client: TestClient, content: bytes, filename: str, **params: object):
    return client.post(
        "/api/v1/imports/employees",
        params=params,
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_employees_csv_dry_run_returns_preview(api) -> None:
    client, factory, _ = api
    content = employee_csv(
        [
            "E-1;Pérez;Juan;20-12345678-6;15/03/2024;Administrativo;CCT 130/75;"
            "juan.perez@example.com"
        ]
    )

    response = _post_employee_file(client, content, "employees.csv")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["kind"] == "employees"
    assert data["dry_run"] is True
    assert data["total"] == 1
    assert data["valid_count"] == 1
    assert data["error_count"] == 0
    assert data["duplicate_count"] == 0
    assert data["missing_columns"] == []
    row = data["valid_rows"][0]
    assert row["legajo"] == "E-1"
    assert row["apellido"] == "Pérez"
    assert row["cuil"] == make_cuil("2012345678")
    assert row["fecha_ingreso"] == "2024-03-15"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Employee)) == 0


def test_employees_xlsx_dry_run_returns_preview(api) -> None:
    client, _, _ = api
    content = make_xlsx(
        EMPLOYEE_HEADERS,
        [
            [
                "E-2",
                "Gómez",
                "Ana",
                make_cuil("2712345678"),
                date(2024, 4, 1),
                "Administrativa",
                "CCT 130/75",
                "ana.gomez@example.com",
            ]
        ],
    )

    response = _post_employee_file(client, content, "employees.xlsx")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert data["valid_count"] == 1
    assert data["errors"] == []
    assert data["valid_rows"][0]["legajo"] == "E-2"
    assert data["valid_rows"][0]["fecha_ingreso"] == "2024-04-01"


def test_invalid_extension_and_empty_files_are_rejected(api) -> None:
    client, _, _ = api

    unsupported = _post_employee_file(client, b"legajo\n1\n", "employees.txt")
    assert unsupported.status_code == 400
    assert "Extension" in unsupported.json()["detail"]

    empty = _post_employee_file(client, b"   \n", "employees.csv")
    assert empty.status_code == 400
    assert "vacio" in empty.json()["detail"]

    binary = _post_employee_file(client, b"legajo\x00\x01\x02", "employees.csv")
    assert binary.status_code == 400
    assert "codificacion" in binary.json()["detail"]


def test_corrupt_xlsx_is_rejected(api) -> None:
    client, _, _ = api

    response = _post_employee_file(client, b"esto no es un xlsx", "employees.xlsx")

    assert response.status_code == 400
    assert "XLSX" in response.json()["detail"]


def test_file_over_size_limit_is_rejected(api) -> None:
    client, _, _ = api
    content = b"a" * (MAX_IMPORT_BYTES + 1)

    response = _post_employee_file(client, content, "employees.csv")

    assert response.status_code == 413
    assert "5 MB" in response.json()["detail"]


def test_novelties_dry_run_returns_preview(api) -> None:
    client, _, _ = api
    content = novelty_csv(["1;202601;horas_extra;10;1500,50"])

    response = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "true"},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["kind"] == "novelties"
    assert data["dry_run"] is True
    assert data["total"] == 1
    assert data["valid_count"] == 1
    assert data["errors"] == []
    assert data["valid_rows"][0]["legajo"] == "1"
    assert data["valid_rows"][0]["periodo"] == "202601"
    assert data["valid_rows"][0]["tipo"] == "horas_extra"


def test_novelties_commit_persists_and_is_idempotent(api) -> None:
    client, factory, _ = api
    employee_id = add_employee(factory, "E-30")
    content = novelty_csv(
        [
            "E-30;202601;horas_extra;10;1500,50",
            "E-30;202601;ausencia;2;",
        ]
    )

    first = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false"},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["kind"] == "novelties"
    assert first_data["dry_run"] is False
    assert first_data["created"] == 2
    assert first_data["skipped"] == 0
    assert first_data["valid_count"] == 2
    assert first_data["error_count"] == 0
    assert first_data["duplicate_count"] == 0
    assert first_data["source"] == "import"

    with factory() as session:
        rows = session.scalars(
            select(PayrollNovelty).order_by(PayrollNovelty.id)
        ).all()
        assert len(rows) == 2
        overtime = rows[0]
        assert overtime.organization_id == 1
        assert overtime.employee_id == employee_id
        assert overtime.period == "202601"
        assert overtime.code == "horas_extra"
        assert overtime.kind == "REMUNERATIVE"
        assert overtime.quantity == Decimal("10")
        assert overtime.amount == Decimal("1500.50")
        assert overtime.unit is None
        assert overtime.description is None
        assert overtime.source == "import"
        assert overtime.external_id is None
        assert overtime.created_at is not None
        absence = rows[1]
        assert absence.code == "ausencia"
        assert absence.quantity == Decimal("2")
        assert absence.amount is None

    second = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false"},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["created"] == 0
    assert second_data["skipped"] == 2
    assert second_data["duplicate_count"] == 2
    assert {item["key"] for item in second_data["duplicates"]} == {
        "legajo:E-30|periodo:202601|tipo:horas_extra",
        "legajo:E-30|periodo:202601|tipo:ausencia",
    }
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PayrollNovelty)) == 2


def test_novelties_commit_reports_unknown_legajo_without_aborting(api) -> None:
    client, factory, _ = api
    employee_id = add_employee(factory, "E-31")
    content = novelty_csv(
        [
            "E-999;202601;horas_extra;5;100",
            "E-31;202601;horas_extra;5;100",
        ]
    )

    response = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false"},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert data["valid_count"] == 2
    assert data["error_count"] == 1
    assert data["errors"][0]["code"] == "legajo_no_encontrado"
    assert data["errors"][0]["field"] == "legajo"
    assert data["errors"][0]["value"] == "E-999"
    with factory() as session:
        rows = session.scalars(select(PayrollNovelty)).all()
        assert len(rows) == 1
        assert rows[0].employee_id == employee_id


def test_novelties_commit_is_isolated_by_organization(api) -> None:
    client, factory, _ = api
    with factory.begin() as session:
        session.add(Organization(id=2, name="Otra Organizacion", slug="otra"))
        company = Company(
            organization_id=1,
            cuit="30711223344",
            legal_name="Empresa Propia SA",
        )
        foreign_company = Company(
            organization_id=2,
            cuit="30799999999",
            legal_name="Empresa Ajena SA",
        )
        session.add_all([company, foreign_company])
        session.flush()
        company_id = company.id
        foreign_company_id = foreign_company.id
    foreign_employee_id = add_employee(factory, "E-40", organization_id=2)
    content = novelty_csv(["E-40;202601;horas_extra;7;200"])

    foreign = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false", "company_id": company_id},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert foreign.status_code == 200, foreign.text
    foreign_data = foreign.json()
    assert foreign_data["created"] == 0
    assert foreign_data["error_count"] == 1
    assert foreign_data["errors"][0]["code"] == "legajo_no_encontrado"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PayrollNovelty)) == 0
        assert session.get(Employee, foreign_employee_id) is not None

    local_employee_id = add_employee(factory, "E-40", organization_id=1)
    local = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false", "company_id": company_id},
        files={"file": ("novelties.csv", content, "text/csv")},
    )

    assert local.status_code == 200, local.text
    local_data = local.json()
    assert local_data["created"] == 1
    assert local_data["company_id"] == company_id
    with factory() as session:
        novelty = session.scalar(select(PayrollNovelty))
        assert novelty is not None
        assert novelty.organization_id == 1
        assert novelty.employee_id == local_employee_id

    missing = client.post(
        "/api/v1/imports/novelties",
        params={"dry_run": "false", "company_id": foreign_company_id},
        files={"file": ("novelties.csv", content, "text/csv")},
    )
    assert missing.status_code == 404


def test_employees_commit_is_idempotent(api) -> None:
    client, factory, _ = api
    content = employee_csv(
        ["E-10;Sosa;María;20-12345678-6;15/03/2024;Administrativa;CCT 130/75;maria@example.com"]
    )

    first = _post_employee_file(client, content, "employees.csv", dry_run="false")
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["dry_run"] is False
    assert first_data["created"] == 1
    assert first_data["skipped"] == 0
    assert first_data["valid_count"] == 1
    assert first_data["error_count"] == 0
    assert first_data["duplicate_count"] == 0
    assert first_data["contracts_created"] == 0

    with factory() as session:
        employees = session.scalars(select(Employee)).all()
        assert len(employees) == 1
        employee = employees[0]
        assert employee.organization_id == 1
        assert employee.employee_code == "E-10"
        assert employee.first_name == "María"
        assert employee.last_name == "Sosa"
        assert employee.cuil == make_cuil("2012345678")
        assert employee.hire_date == date(2024, 3, 15)
        assert session.scalar(select(func.count()).select_from(EmploymentContract)) == 0

    second = _post_employee_file(client, content, "employees.csv", dry_run="false")
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["created"] == 0
    assert second_data["skipped"] == 1
    assert second_data["duplicate_count"] == 1
    assert second_data["duplicates"][0]["key"] == "legajo:E-10"

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Employee)) == 1


def test_employees_commit_reports_invalid_rows_without_aborting(api) -> None:
    client, factory, _ = api
    content = employee_csv(
        [
            "E-11;Mal;Cuil;20-12345678-9;15/03/2024;;;mal@example.com",
            f"E-12;Válida;Fila;{make_cuil('2712345678')};16/03/2024;;;ok@example.com",
        ]
    )

    response = _post_employee_file(client, content, "employees.csv", dry_run="false")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["created"] == 1
    assert data["valid_count"] == 1
    assert data["error_count"] == 1
    assert data["errors"][0]["code"] == "cuil_invalido"
    with factory() as session:
        codes = session.scalars(select(Employee.employee_code)).all()
        assert codes == ["E-12"]


def test_employees_commit_continues_after_db_conflict(api) -> None:
    client, factory, _ = api
    repeated_cuil = make_cuil("2012345678")
    content = employee_csv(
        [
            f"E-20;Uno;Cuil;{repeated_cuil};15/03/2024;;;uno@example.com",
            f"E-21;Dos;Cuil;{repeated_cuil};16/03/2024;;;dos@example.com",
            f"E-22;Tres;Cuil;{make_cuil('2712345678')};17/03/2024;;;tres@example.com",
        ]
    )

    response = _post_employee_file(client, content, "employees.csv", dry_run="false")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 2
    assert data["valid_count"] == 3
    assert data["error_count"] == 1
    assert data["errors"][0]["code"] == "conflicto_bd"
    with factory() as session:
        codes = session.scalars(select(Employee.employee_code).order_by(Employee.id)).all()
        assert codes == ["E-20", "E-22"]


def test_employees_commit_creates_contract_when_company_is_provided(api) -> None:
    client, factory, _ = api
    with factory.begin() as session:
        company = Company(
            organization_id=1,
            cuit="30711223344",
            legal_name="Empresa SA",
        )
        session.add(company)
        session.flush()
        company_id = company.id

    content = employee_csv(
        ["E-13;López;Pedro;20-12345678-6;20/05/2024;;;pedro@example.com"]
    )

    response = _post_employee_file(
        client, content, "employees.csv", dry_run="false", company_id=company_id
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 1
    assert data["contracts_created"] == 1
    with factory() as session:
        employee = session.scalar(select(Employee).where(Employee.employee_code == "E-13"))
        assert employee is not None
        contract = session.scalar(
            select(EmploymentContract).where(EmploymentContract.employee_id == employee.id)
        )
        assert contract is not None
        assert contract.company_id == company_id
        assert contract.valid_from == date(2024, 5, 20)


def test_imports_require_authentication(api) -> None:
    client, _, application = api
    content = employee_csv(
        ["E-14;Anónimo;Sin Sesión;20-12345678-6;15/03/2024;;;anon@example.com"]
    )
    application.dependency_overrides.pop(require_user)

    employee_response = _post_employee_file(client, content, "employees.csv")
    novelty_response = client.post(
        "/api/v1/imports/novelties",
        files={"file": ("novelties.csv", novelty_csv(["1;202601;horas_extra;10;"]), "text/csv")},
    )

    assert employee_response.status_code == 401
    assert novelty_response.status_code == 401


def test_viewer_can_preview_but_cannot_commit(api) -> None:
    client, factory, application = api
    viewer = User(
        id=2,
        organization_id=1,
        email="viewer@example.test",
        password_hash="not-used-in-tests",
        role="viewer",
        active=True,
    )
    application.dependency_overrides[require_user] = lambda: viewer
    content = employee_csv(
        ["E-15;Vista;Solo;20-12345678-6;15/03/2024;;;vista@example.com"]
    )

    preview = _post_employee_file(client, content, "employees.csv", dry_run="true")
    commit = _post_employee_file(client, content, "employees.csv", dry_run="false")

    assert preview.status_code == 200
    assert commit.status_code == 403
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Employee)) == 0
