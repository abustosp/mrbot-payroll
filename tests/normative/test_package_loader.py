"""Tests for the validated CCT package loader and its admin API."""

from __future__ import annotations

import copy
import json
from collections.abc import Generator
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import normative_packages
from app.auth.dependencies import require_user
from app.core.normative.package_loader import PackageValidationError, load_cct_catalog
from app.database import Base
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    NormativeDocument,
    NormativeParameter,
    SalaryScale,
)
from app.database.session import get_db


def minimal_catalog() -> dict:
    """Self-contained fixture: the real ``normative/cct`` package is optional."""

    return {
        "schema_version": "1.0",
        "ccts": [
            {
                "code": "130/75",
                "name": "Empleados de Comercio",
                "activity": "Comercio",
                "scope": "Ámbito nacional",
                "source_urls": [
                    "https://www.argentina.gob.ar/trabajo/cct-130-75",
                ],
                "pdf_path": "normative/cct/pdfs/130-75.pdf",
                "pdf_sha256": "a" * 64,
                "pdf_status": "verified",
                "published_at": "2025-05-02",
                "categories": [
                    {
                        "code": "ADMIN_A",
                        "name": "Administrativo A",
                        "description": "Categoría administrativa",
                    },
                    {"code": "ADMIN_B", "name": "Administrativo B"},
                ],
                "salary_scales": [
                    {
                        "category": "ADMIN_A",
                        "amount": "850000.00",
                        "currency": "ARS",
                        "valid_from": "2025-05-01",
                        "valid_to": "2025-05-31",
                        "source": "Resolución 1/2025, página 4",
                        "status": "verified",
                    },
                    {
                        "category": "ADMIN_B",
                        "amount": "900000.50",
                        "currency": "ARS",
                        "valid_from": "2025-05-01",
                        "valid_to": "2025-05-31",
                        "source": "Resolución 1/2025, página 4",
                        "status": "verified",
                    },
                ],
                "parameters": [
                    {
                        "code": "cct13075.seniority_rate",
                        "value": "0.01",
                        "valid_from": "2025-05-01",
                        "valid_to": "2025-05-31",
                        "published_at": "2025-05-02",
                        "version": 1,
                        "source": "Resolución 1/2025",
                    }
                ],
                "formula_codes": ["SUELDO_BASICO"],
                "confidence": "high",
                "notes": "Fixture de test; no representa normativa vigente.",
            }
        ],
    }


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'packages.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'packages-api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    application = FastAPI()
    application.include_router(normative_packages.router, prefix="/api/v1")
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[require_user] = lambda: SimpleNamespace(
        role="admin", active=True
    )
    with TestClient(application) as client:
        yield client, local_session
    application.dependency_overrides.clear()
    engine.dispose()


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_valid_catalog_dry_run_then_commit(session: Session) -> None:
    catalog = minimal_catalog()

    preview = load_cct_catalog(session, catalog)
    assert preview.dry_run is True
    assert preview.agreements.created == 1
    assert preview.categories.created == 2
    assert preview.scales.created == 2
    assert preview.parameters.created == 1
    assert preview.documents.created == 1
    assert preview.created == 7
    assert preview.warnings == ()
    assert _count(session, CollectiveAgreement) == 0
    assert _count(session, SalaryScale) == 0

    result = load_cct_catalog(session, catalog, dry_run=False)
    session.commit()

    assert result.dry_run is False
    assert result.agreements.created == 1
    assert _count(session, CollectiveAgreement) == 1
    assert _count(session, AgreementCategory) == 2
    assert _count(session, SalaryScale) == 2
    assert _count(session, NormativeParameter) == 1
    assert _count(session, NormativeDocument) == 1

    agreement = session.scalar(select(CollectiveAgreement))
    assert agreement is not None
    assert agreement.code == "130/75"
    assert agreement.year == 1975
    assert agreement.name == "Empleados de Comercio"
    assert agreement.activity == "Comercio"

    categories = session.scalars(
        select(AgreementCategory).order_by(AgreementCategory.code)
    ).all()
    assert [category.code for category in categories] == ["ADMIN_A", "ADMIN_B"]
    assert categories[0].description == "Categoría administrativa"

    scales = session.scalars(select(SalaryScale).order_by(SalaryScale.category_id)).all()
    assert [scale.base_salary for scale in scales] == [
        Decimal("850000.00"),
        Decimal("900000.50"),
    ]
    assert all(scale.valid_to is not None for scale in scales)

    document = session.scalar(select(NormativeDocument))
    assert document is not None
    assert document.checksum == "a" * 64
    assert document.file_path == "normative/cct/pdfs/130-75.pdf"
    assert document.published_at is not None
    assert scales[0].source_document_id == document.id

    parameter = session.scalar(select(NormativeParameter))
    assert parameter is not None
    assert parameter.code == "cct13075.seniority_rate"
    assert parameter.value == Decimal("0.0100")
    assert parameter.source_document_id == document.id


def test_reimport_is_idempotent_and_preserves_history(session: Session) -> None:
    catalog = minimal_catalog()
    load_cct_catalog(session, catalog, dry_run=False)
    session.commit()

    second = load_cct_catalog(session, catalog, dry_run=False)
    session.commit()

    assert second.created == 0
    assert second.updated == 0
    assert second.agreements.unchanged == 1
    assert second.categories.unchanged == 2
    assert second.scales.unchanged == 2
    assert second.parameters.unchanged == 1
    assert second.documents.unchanged == 1
    assert _count(session, CollectiveAgreement) == 1
    assert _count(session, SalaryScale) == 2
    assert _count(session, NormativeDocument) == 1

    changed = copy.deepcopy(catalog)
    changed["ccts"][0]["salary_scales"][0]["amount"] = "860000.00"
    third = load_cct_catalog(session, changed, dry_run=False)
    session.commit()

    assert third.scales.updated == 1
    assert _count(session, SalaryScale) == 2
    values = session.scalars(select(SalaryScale.base_salary).order_by(SalaryScale.id)).all()
    assert Decimal("860000.00") in values


def test_rejects_overlapping_scales_in_package(session: Session) -> None:
    catalog = minimal_catalog()
    catalog["ccts"][0]["salary_scales"].append(
        {
            "category": "ADMIN_A",
            "amount": "860000.00",
            "valid_from": "2025-05-15",
            "valid_to": "2025-06-15",
            "source": "Otra resolución",
        }
    )

    with pytest.raises(PackageValidationError, match="superpuestas"):
        load_cct_catalog(session, catalog)
    assert _count(session, SalaryScale) == 0


def test_rejects_scale_overlapping_with_existing_row(session: Session) -> None:
    load_cct_catalog(session, minimal_catalog(), dry_run=False)
    session.commit()

    catalog = minimal_catalog()
    catalog["ccts"][0]["salary_scales"] = [
        {
            "category": "ADMIN_A",
            "amount": "860000.00",
            "valid_from": "2025-05-15",
            "valid_to": "2025-06-15",
            "source": "Resolución 2/2025",
        }
    ]
    with pytest.raises(PackageValidationError, match="se solapa con"):
        load_cct_catalog(session, catalog)
    assert _count(session, SalaryScale) == 2


@pytest.mark.parametrize("amount", ["no-es-un-numero", "-1", "NaN"])
def test_rejects_invalid_amounts(session: Session, amount: str) -> None:
    catalog = minimal_catalog()
    catalog["ccts"][0]["salary_scales"][0]["amount"] = amount

    with pytest.raises(PackageValidationError, match="importe"):
        load_cct_catalog(session, catalog)
    assert _count(session, SalaryScale) == 0


def test_rejects_invalid_checksum(session: Session) -> None:
    catalog = minimal_catalog()
    catalog["ccts"][0]["pdf_sha256"] = "not-a-sha256"

    with pytest.raises(PackageValidationError, match="checksum"):
        load_cct_catalog(session, catalog)


def test_rejects_parameter_overlap(session: Session) -> None:
    catalog = minimal_catalog()
    first = catalog["ccts"][0]["parameters"][0]
    catalog["ccts"][0]["parameters"].append(
        {
            **first,
            "value": "0.02",
            "version": 2,
            "valid_from": "2025-05-15",
            "valid_to": "2025-06-15",
        }
    )

    with pytest.raises(PackageValidationError, match="Parámetros superpuestos"):
        load_cct_catalog(session, catalog)


def test_adjacent_inclusive_validities_are_accepted(session: Session) -> None:
    catalog = minimal_catalog()
    catalog["ccts"][0]["salary_scales"][0]["valid_to"] = "2025-05-31"
    catalog["ccts"][0]["salary_scales"].append(
        {
            "category": "ADMIN_A",
            "amount": "860000.00",
            "valid_from": "2025-06-01",
            "valid_to": "2025-06-30",
            "source": "Resolución 2/2025",
        }
    )
    catalog["ccts"][0]["parameters"].append(
        {
            "code": "cct13075.seniority_rate",
            "value": "0.02",
            "valid_from": "2025-06-01",
            "valid_to": "2025-06-30",
            "version": 2,
            "source": "Resolución 2/2025",
        }
    )

    result = load_cct_catalog(session, catalog)
    assert result.scales.created == 3
    assert result.parameters.created == 2


def test_import_endpoint_defaults_to_dry_run_and_commits(api) -> None:
    client, local_session = api
    catalog = minimal_catalog()

    preview = client.post("/api/v1/normative-packages/import", json={"catalog": catalog})
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    with local_session() as db:
        assert _count(db, CollectiveAgreement) == 0
        assert _count(db, SalaryScale) == 0

    committed = client.post(
        "/api/v1/normative-packages/import",
        json={"catalog": catalog, "dry_run": False},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["dry_run"] is False
    assert committed.json()["summary"]["created"] == 7
    with local_session() as db:
        assert _count(db, CollectiveAgreement) == 1
        assert _count(db, SalaryScale) == 2

    listing = client.get("/api/v1/normative-packages/ccts")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "130/75"
    assert body["items"][0]["category_count"] == 2
    assert body["items"][0]["salary_scale_count"] == 2


@pytest.mark.parametrize(
    "path",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "normative/cct/../../.env.example",
        "normative/cct/pdfs/../../../../etc/passwd",
    ],
)
def test_import_endpoint_rejects_paths_outside_cct_dir(api, path: str) -> None:
    client, _ = api
    response = client.post(
        "/api/v1/normative-packages/import", json={"path": path}
    )
    assert response.status_code == 400, response.text


def test_import_endpoint_requires_exactly_one_source(api) -> None:
    client, _ = api
    missing = client.post("/api/v1/normative-packages/import", json={})
    assert missing.status_code == 422
    both = client.post(
        "/api/v1/normative-packages/import",
        json={"catalog": minimal_catalog(), "path": "catalog.json"},
    )
    assert both.status_code == 422


def test_import_endpoint_reads_json_inside_cct_dir(api, tmp_path, monkeypatch) -> None:
    client, _ = api
    allowed = tmp_path / "normative" / "cct"
    allowed.mkdir(parents=True)
    package_path = allowed / "catalog.json"
    package_path.write_text(json.dumps(minimal_catalog()), encoding="utf-8")
    monkeypatch.setattr(normative_packages, "NORMATIVE_CCT_DIR", allowed)

    response = client.post(
        "/api/v1/normative-packages/import", json={"path": str(package_path)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True
