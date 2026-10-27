"""Pins de datos fix2 (V2-06, V2-07, V2-20, V2-21, V2-23, V2-24, B-27, B-42P).

Cada test fija un ítem del delta 00 con el fix mínimo correspondiente.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.common import commit_or_conflict
from app.auth.service import seed_admin
from app.database import Base
from app.database.base import ensure_utc, utc_now
from app.database.guards import ContractInUseError, ScaleInUseError
from app.database.models import (
    AgreementCategory,
    AuditLog,
    CollectiveAgreement,
    EmploymentContract,
    FormulaDefinition,
    FormulaVersion,
    PayrollConcept,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    Ruleset,
    SalaryScale,
)
from app.database.session import get_db
from app.main import app

PASSWORD = "a-long-test-password"


def _fk_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture
def db_factory(tmp_path):
    from scripts.seed_demo import seed

    engine = _fk_engine(f"sqlite:///{tmp_path / 'fix2-datos.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        demo = seed(session)
        context = {
            "organization_id": demo["organization"].id,
            "company_id": demo["company"].id,
            "admin_id": demo["admin"].id,
            "employee_ids": [employee.id for employee in demo["employees"]],
        }
    yield factory, context
    engine.dispose()


@pytest.fixture
def api(tmp_path):
    engine = _fk_engine(f"sqlite:///{tmp_path / 'fix2-v220.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        seed_admin(db, "admin@example.test", PASSWORD)
    with TestClient(app) as client:
        yield client, local_session
    app.dependency_overrides.clear()
    engine.dispose()


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.test", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


# V2-06 ---------------------------------------------------------------------


def test_v206_escala_en_uso_no_se_borra(db_factory) -> None:
    """V2-06: borrar una escala con contratos activos vigentes falla con pin."""
    factory, _ = db_factory
    with factory() as session:
        scale = session.scalar(select(SalaryScale).order_by(SalaryScale.id))
        assert scale is not None
        session.delete(scale)
        with pytest.raises(ScaleInUseError):
            session.flush()
        session.rollback()


def test_v206_escala_sin_uso_se_borra(db_factory) -> None:
    """V2-06: una escala sin contratos activos se borra sin traba."""
    factory, _ = db_factory
    with factory.begin() as session:
        agreement = CollectiveAgreement(code="SIN-USO", year=2026, name="Sin uso")
        session.add(agreement)
        session.flush()
        category = AgreementCategory(
            agreement_id=agreement.id, code="U1", name="Sin uso 1"
        )
        session.add(category)
        session.flush()
        scale = SalaryScale(
            category_id=category.id,
            valid_from=date(2026, 1, 1),
            base_salary=Decimal("100000.00"),
        )
        session.add(scale)
        session.flush()
        scale_id = scale.id
    with factory.begin() as session:
        row = session.get(SalaryScale, scale_id)
        assert row is not None
        session.delete(row)


# V2-07 ---------------------------------------------------------------------


def test_v207_contrato_activo_no_se_borra(db_factory) -> None:
    """V2-07: un contrato activo exige baja lógica antes del DELETE físico."""
    factory, _ = db_factory
    with factory() as session:
        contract = session.scalar(
            select(EmploymentContract)
            .where(EmploymentContract.active.is_(True))
            .order_by(EmploymentContract.id)
        )
        assert contract is not None
        session.delete(contract)
        with pytest.raises(ContractInUseError):
            session.flush()
        session.rollback()


def test_v207_contrato_inactivo_se_borra(db_factory) -> None:
    """V2-07: con active=false (respetado por el cálculo) el DELETE procede."""
    factory, _ = db_factory
    with factory.begin() as session:
        contract = session.scalar(
            select(EmploymentContract)
            .where(EmploymentContract.active.is_(True))
            .order_by(EmploymentContract.id)
        )
        assert contract is not None
        contract.active = False
        session.flush()
        contract_id = contract.id
    with factory.begin() as session:
        row = session.get(EmploymentContract, contract_id)
        assert row is not None
        session.delete(row)
    with factory() as session:
        assert session.get(EmploymentContract, contract_id) is None


# V2-20 ---------------------------------------------------------------------


def test_v220_draft_no_bloquea_borrado_concepto(api) -> None:
    """V2-20: una fórmula DRAFT no impide borrar el concepto (204)."""
    client, _ = api
    _login(client)
    concept = client.post(
        "/api/v1/concepts",
        json={"code": "BORR", "name": "Borrable", "nature": "REMUNERATIVE"},
    )
    assert concept.status_code == 201, concept.text
    formula = client.post(
        "/api/v1/formulas",
        json={"code": "REFBORR", "formula": {"concept": "BORR"}},
    )
    assert formula.status_code == 201, formula.text
    assert formula.json()["status"] == "DRAFT"

    response = client.delete(f"/api/v1/concepts/{concept.json()['id']}")
    assert response.status_code == 204, response.text


def test_v220_approved_bloquea_con_409(api) -> None:
    """V2-20: una fórmula APPROVED bloquea con 409 que nombra el estado."""
    client, local_session = api
    _login(client)
    concept = client.post(
        "/api/v1/concepts",
        json={"code": "FIJO", "name": "Fijo", "nature": "REMUNERATIVE"},
    )
    assert concept.status_code == 201, concept.text
    formula = client.post(
        "/api/v1/formulas",
        json={"code": "REFFIJO", "formula": {"concept": "FIJO"}},
    )
    assert formula.status_code == 201, formula.text
    formula_id = formula.json()["id"]
    with local_session.begin() as db:
        row = db.scalar(
            select(FormulaVersion).where(FormulaVersion.formula_id == formula_id)
        )
        assert row is not None
        row.status = "APPROVED"

    response = client.delete(f"/api/v1/concepts/{concept.json()['id']}")
    assert response.status_code == 409, response.text
    assert "APROBADA" in response.text
    assert client.get(f"/api/v1/concepts/{concept.json()['id']}").status_code == 200


# V2-21 ---------------------------------------------------------------------


def test_v221_indices_fk_calientes_existen() -> None:
    """V2-21: las 4 FK calientes tienen índice propio en el modelo."""
    assert "ix_payroll_results_employee_id" in {
        index.name for index in PayrollResult.__table__.indexes
    }
    names_items = {index.name for index in PayrollItem.__table__.indexes}
    assert "ix_payroll_items_result_id" in names_items
    assert "ix_payroll_items_concept_id" in names_items
    assert "ix_audit_logs_organization_id" in {
        index.name for index in AuditLog.__table__.indexes
    }


# V2-23 ---------------------------------------------------------------------


def test_v223_ensure_utc_normaliza_y_documenta_comparar_fechas(
    db_factory,
) -> None:
    """V2-23: utc_now es aware; ensure_utc rescata lecturas naive de SQLite."""
    assert utc_now().tzinfo is not None
    assert ensure_utc(None) is None
    naive = datetime(2026, 6, 30, 12, 0, 0)
    fixed = ensure_utc(naive)
    assert fixed is not None and fixed.tzinfo == UTC
    aware = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    assert ensure_utc(aware) == aware
    # SQLite persiste aware pero lee naive: la comparación directa revienta,
    # por eso el negocio compara fechas o normaliza con ensure_utc.
    with pytest.raises(TypeError):
        assert aware > naive  # type: ignore[operator]
    assert ensure_utc(naive) is not None
    factory, context = db_factory
    with factory() as session:
        from app.database.models import Organization

        org = session.get(Organization, context["organization_id"])
        assert org is not None
        assert ensure_utc(org.created_at) is not None
        assert ensure_utc(org.created_at).tzinfo == UTC  # type: ignore[union-attr]


# V2-24 ---------------------------------------------------------------------


def test_v224_borrado_orm_deja_corrida_en_error_por_empleado(
    db_factory,
) -> None:
    """V2-24: borrar concepto por ORM no rompe; la corrida va a ERROR."""
    from app.services.payroll_calculation import calculate_payroll_run

    factory, context = db_factory
    with factory.begin() as session:
        concept = session.scalar(
            select(PayrollConcept).where(
                PayrollConcept.organization_id == context["organization_id"],
                PayrollConcept.code == "BASICO",
            )
        )
        assert concept is not None
        session.delete(concept)
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="v224-orm",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        run_id = run.id
    with factory() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        try:
            result = calculate_payroll_run(session, run)
        except Exception:
            session.rollback()
            raise
        session.commit()
    assert result["status"] == "ERROR"
    assert result["results"] == []
    assert len(result["errors"]) == 2
    assert all("BASICO" in error["message"] for error in result["errors"])


# B-27 ----------------------------------------------------------------------


def test_b27_snapshot_incluye_escalas_y_contratos(db_factory) -> None:
    """B-27: cada cálculo sella escalas y contratos vigentes del período."""
    from app.services.payroll_calculation import calculate_payroll_run
    from scripts.seed_demo import DEMO_END, DEMO_START

    factory, context = db_factory
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="b27-snap",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        run_id = run.id
    with factory() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        try:
            result = calculate_payroll_run(session, run)
        except Exception:
            session.rollback()
            raise
        session.commit()
        ruleset_id = result["ruleset_id"]
    assert result["status"] == "CALCULATED"
    with factory() as session:
        sealed = session.get(Ruleset, ruleset_id)
        assert sealed is not None
        assert "scales" in sealed.rules and "contracts" in sealed.rules
        assert len(sealed.rules["scales"]) >= 2
        assert len(sealed.rules["contracts"]) >= 2
        assert {entry["category_id"] for entry in sealed.rules["scales"]} >= {
            entry["category_id"] for entry in sealed.rules["contracts"]
        }
        for entry in sealed.rules["scales"]:
            assert DEMO_START.isoformat() <= entry["valid_from"] <= DEMO_END.isoformat()
        assert sealed.rules["inputs_hash"] == result["inputs_hash"]


# B-42P ---------------------------------------------------------------------


def test_b42p_concepto_con_items_no_se_borra(db_factory) -> None:
    """B-42P resto: un concepto con ítems liquidados se bloquea (FK)."""
    from app.services.payroll_calculation import calculate_payroll_run

    factory, context = db_factory
    with factory.begin() as session:
        run = PayrollRun(
            organization_id=context["organization_id"],
            company_id=context["company_id"],
            code="b42p-items",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            run_type="MONTHLY",
            status="DRAFT",
            created_by=context["admin_id"],
        )
        session.add(run)
        session.flush()
        run_id = run.id
    with factory() as session:
        run = session.get(PayrollRun, run_id)
        assert run is not None
        try:
            result = calculate_payroll_run(session, run)
        except Exception:
            session.rollback()
            raise
        session.commit()
    assert result["status"] == "CALCULATED"
    with factory() as session:
        assert session.scalar(select(PayrollItem).limit(1)) is not None
        concept = session.scalar(
            select(PayrollConcept).where(
                PayrollConcept.organization_id == context["organization_id"],
                PayrollConcept.code == "BASICO",
            )
        )
        assert concept is not None
        session.delete(concept)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_formula_definition_sin_usar() -> None:
    """Guarda: el import del módulo de fórmulas no usado no rompe el pin."""
    assert FormulaDefinition.__tablename__ == "formula_definitions"


def test_guard_escala_mapea_409(db_factory) -> None:
    """commit_or_conflict mapea ScaleInUseError a HTTP 409."""
    factory, _ = db_factory
    with factory() as session:
        scale = session.scalar(select(SalaryScale).order_by(SalaryScale.id))
        assert scale is not None
        session.delete(scale)
        with pytest.raises(HTTPException) as exc_info:
            commit_or_conflict(session)
        assert exc_info.value.status_code == 409
        assert f"escala {scale.id}" in str(exc_info.value.detail)


def test_guard_contrato_mapea_409(db_factory) -> None:
    """commit_or_conflict mapea ContractInUseError a HTTP 409."""
    factory, _ = db_factory
    with factory() as session:
        contract = session.scalar(
            select(EmploymentContract)
            .where(EmploymentContract.active.is_(True))
            .order_by(EmploymentContract.id)
        )
        assert contract is not None
        session.delete(contract)
        with pytest.raises(HTTPException) as exc_info:
            commit_or_conflict(session)
        assert exc_info.value.status_code == 409
        assert f"contrato {contract.id}" in str(exc_info.value.detail)
