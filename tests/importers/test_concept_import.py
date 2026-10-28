"""Importacion de conceptos desde CSV/XLSX (preview + commit)."""

from __future__ import annotations

from collections.abc import Generator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.imports import router
from app.auth.dependencies import require_user
from app.database import Base
from app.database.models import Organization, PayrollConcept, User
from app.database.session import get_db
from app.importers import analyze_file

CONCEPT_HEADERS = ["Codigo", "Nombre", "Naturaleza", "Descripcion"]


def concept_csv(rows: list[str]) -> bytes:
    return ("\n".join([";".join(CONCEPT_HEADERS), *rows]) + "\n").encode("utf-8")


def test_csv_valido_conceptos() -> None:
    content = concept_csv(
        [
            "BASICO;Sueldo básico;remunerativo;Haber mensual",
            "PRESENTISMO;Presentismo;;",
        ]
    )

    preview = analyze_file(BytesIO(content), "concepts")

    assert preview.kind == "concepts"
    assert preview.total == 2
    assert preview.dry_run is True
    assert preview.errors == []
    assert preview.duplicates == []
    assert preview.missing_columns == []
    assert preview.valid_rows[0].codigo == "BASICO"
    assert preview.valid_rows[0].naturaleza == "REMUNERATIVE"
    # Naturaleza vacia cae al default remunerativo.
    assert preview.valid_rows[1].naturaleza == "REMUNERATIVE"


def test_naturaleza_invalida_y_duplicado() -> None:
    content = concept_csv(
        [
            "X1;Uno;invalida;",
            "X1;Dos;descuento;",
            "X1;Tres;descuento;",
        ]
    )

    preview = analyze_file(BytesIO(content), "concepts")

    assert len(preview.valid_rows) == 1
    assert any(error.field == "naturaleza" for error in preview.errors)
    assert len(preview.duplicates) == 1


def test_columna_faltante_cita_cabecera() -> None:
    content = b"Codigo;Naturaleza\nX1;descuento\n"

    preview = analyze_file(BytesIO(content), "concepts")

    assert preview.valid_rows == []
    assert preview.missing_columns == ["nombre"]
    assert any(
        error.code == "columna_faltante" and "Codigo;Nombre" in error.message
        for error in preview.errors
    )


@pytest.fixture
def api(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'imports-concepts.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id=1, name="Org Test", slug="test"))

    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    admin = User(
        id=1,
        organization_id=1,
        email="admin@example.test",
        password_hash="x",
        role="admin",
        active=True,
    )
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_user] = lambda: admin
    with TestClient(application) as client:
        yield client, factory
    application.dependency_overrides.clear()
    engine.dispose()


def test_commit_crea_y_omite_duplicados(api) -> None:
    client, factory = api
    content = concept_csv(
        [
            "BASICO;Sueldo básico;remunerativo;",
            "JUB;Descuento jubilatorio;descuento;",
        ]
    )
    files = {"file": ("conceptos.csv", content, "text/csv")}

    preview = client.post("/api/v1/imports/concepts", files=files)
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_count"] == 2

    committed = client.post(
        "/api/v1/imports/concepts", params={"dry_run": False}, files=files
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["created"] == 2

    again = client.post(
        "/api/v1/imports/concepts", params={"dry_run": False}, files=files
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    assert again.json()["skipped"] == 2

    with factory() as session:
        codes = set(session.scalars(select(PayrollConcept.code)).all())
    assert {"BASICO", "JUB"} <= codes
