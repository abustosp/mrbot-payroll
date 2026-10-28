"""Opt-in PostgreSQL migration, lifecycle and deterministic locking checks."""
from __future__ import annotations

import os
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.api import imports as imports_api
from app.api.payroll_runs import approve_payroll_run
from app.config import get_settings
from app.database.models import (
    Company,
    Employee,
    EmploymentContract,
    Organization,
    PayrollNovelty,
    PayrollResult,
    PayrollRun,
    Ruleset,
    User,
)
from app.database.session import get_db
from app.main import app
from app.services import payroll_calculation as calculation
from scripts.seed_demo import seed


@pytest.fixture
def pg(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("PAYROLL_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set PAYROLL_TEST_POSTGRES_URL to run PostgreSQL tests")
    schema = f"payroll_test_{uuid4().hex}"
    admin_engine = create_engine(url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("PAYROLL_DATABASE_URL", scoped_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    engine = create_engine(scoped_url, pool_size=10)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory.begin() as db:
            demo = seed(db)
            ids = {key: demo[key].id for key in ("organization", "company", "admin")}
        yield factory, ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
        get_settings.cache_clear()


def _run(db: Session, ids: dict[str, int], code: str) -> PayrollRun:
    run = PayrollRun(
        organization_id=ids["organization"], company_id=ids["company"], created_by=ids["admin"],
        code=code, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        run_type="MONTHLY", status="DRAFT",
    )
    db.add(run)
    db.flush()
    return run


def test_postgres_migration_preserves_existing_results(pg) -> None:
    factory, ids = pg
    with factory() as db:
        employee_id = db.scalar(select(Employee.id).where(Employee.employee_code == "E-001"))
    config = Config("alembic.ini")
    command.downgrade(config, "i1a2b3c4d5e6")
    with factory.begin() as db:
        run_id = db.scalar(text("""
            INSERT INTO payroll_runs
                (organization_id, company_id, created_by, code, period_start, period_end,
                 run_type, status, created_at)
            VALUES (:org, :company, :admin, 'old', '2026-06-01', '2026-06-30',
                    'MONTHLY', 'APPROVED', now()) RETURNING id
        """), {"org": ids["organization"], "company": ids["company"], "admin": ids["admin"]})
        db.execute(text("""
            INSERT INTO payroll_results
                (payroll_run_id, employee_id, remunerative, non_remunerative, deductions,
                 contributions, gross, net, employer_cost)
            VALUES (:run, :employee, 100, 0, 0, 0, 100, 100, 100)
        """), {"run": run_id, "employee": employee_id})
    command.upgrade(config, "head")
    with factory.begin() as db:
        assert db.scalar(text("SELECT net FROM payroll_results WHERE payroll_run_id = :id"), {"id": run_id}) == 100
        db.execute(text("UPDATE payroll_runs SET status = 'ANNULLED', annulled_reason = 'error', annulled_by = :user WHERE id = :id"), {"user": ids["admin"], "id": run_id})
    with pytest.raises(ValueError, match="revertir"):
        command.downgrade(config, "i1a2b3c4d5e6")
    with factory() as db:
        assert db.scalar(text("SELECT net FROM payroll_results WHERE payroll_run_id = :id"), {"id": run_id}) == 100


def test_postgres_migration_and_monthly_lifecycle(pg) -> None:
    factory, ids = pg
    with factory.begin() as db:
        employee = db.scalar(select(Employee).where(Employee.employee_code == "E-001"))
        second = Company(organization_id=ids["organization"], cuit="30111111111", legal_name="Otra")
        foreign_org = Organization(name="Otra organización", slug="foreign")
        db.add_all([second, foreign_org])
        db.flush()
        foreign_employee = Employee(organization_id=foreign_org.id, employee_code="F-001", first_name="F", last_name="X")
        db.add_all([foreign_employee, EmploymentContract(employee_id=employee.id, company_id=second.id, valid_from=date(2026, 1, 1))])
        legacy = PayrollNovelty(organization_id=ids["organization"], employee_id=employee.id, period="202606", code="LEGACY", source="legacy")
        db.add(legacy)
        db.flush()
        legacy_id, second_id = legacy.id, second.id

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "admin"}).raise_for_status()
        file = "Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\nE-001;202606;BONO;1;100;ok\nF-001;202606;BONO;1;100;ok\n"
        def upload(company_id: int | None):
            query = "?dry_run=false" + (f"&company_id={company_id}" if company_id else "")
            return client.post(f"/api/v1/imports/novelties{query}", files={"file": ("nov.csv", file.encode(), "text/csv")})

        ambiguous = upload(None).json()
        assert {error["code"] for error in ambiguous["errors"]} == {"empresa_ambigua", "legajo_no_encontrado"}
        imported = upload(ids["company"]).json()
        assert imported["created"] == 1
        # A legacy NULL must be resolved before calculation when contracts overlap.
        repaired = client.post(f"/api/v1/imports/novelties/{legacy_id}/repair", json={"company_id": second_id, "reason": "Contrato revisado"})
        assert repaired.status_code == 200, repaired.text
        created = client.post("/api/v1/payroll-runs", json={
            "company_id": ids["company"], "code": "monthly", "period_start": "2026-06-01",
            "period_end": "2026-06-30", "run_type": "MONTHLY",
        })
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        url = f"/api/v1/payroll-runs/{run_id}/calculate?allow_unconsumed_novelties=true"
        first = client.post(url)
        assert first.status_code == 200 and first.json()["status"] == "CALCULATED", first.text
        second_calc = client.post(url)
        assert second_calc.status_code == 200 and second_calc.json()["results_hash"] == first.json()["results_hash"]
        result_id = second_calc.json()["results"][0]["id"]
        assert client.post(f"/api/v1/payroll-runs/{run_id}/approve").status_code == 200
        replacement = client.post(f"/api/v1/payroll-runs/{run_id}/replace", json={"code": "monthly-replacement", "reason": "Corrección"})
        assert replacement.status_code == 200 and replacement.json()["adjusts_run_id"] == run_id, replacement.text
        assert client.get(f"/api/v1/exports/receipts/{result_id}/json").status_code == 409
        with factory() as db:
            assert db.get(PayrollResult, result_id) is not None
            assert db.get(PayrollRun, run_id).status == "ANNULLED"


def test_postgres_same_run_claim_rejects_stale_session(pg, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, ids = pg
    with factory.begin() as db:
        run_id = _run(db, ids, "same").id
    entered, release = Event(), Event()
    original = calculation._run_calculation

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(calculation, "_run_calculation", paused)
    with factory() as stale, ThreadPoolExecutor(max_workers=1) as pool:
        stale_run = stale.get(PayrollRun, run_id)

        def calculate_first():
            with factory() as db:
                response = calculation.calculate_payroll_run(db, db.get(PayrollRun, run_id))
                db.commit()
                return response

        future = pool.submit(calculate_first)
        try:
            assert entered.wait(10)
            with pytest.raises(calculation.PayrollRunStateError):
                calculation.calculate_payroll_run(stale, stale_run)
        finally:
            release.set()
        assert future.result(timeout=15)["status"] == "CALCULATED"


def test_postgres_import_serializes_with_approval(pg, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, ids = pg
    with factory.begin() as db:
        run_id = _run(db, ids, "lock").id
    with factory() as db:
        assert calculation.calculate_payroll_run(db, db.get(PayrollRun, run_id))["status"] == "CALCULATED"
        db.commit()
    entered, release, approval_started = Event(), Event(), Event()
    original = imports_api._invalidate_runs
    approval_pid = []

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(imports_api, "_invalidate_runs", paused)

    def do_import():
        with factory() as db:
            preview = imports_api._analyze(b"Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\nE-001;202606;BONO;1;100;ok\n", "nov.csv", "novelties")
            return imports_api._commit_novelties(db, db.get(User, ids["admin"]), preview, ids["company"])

    def do_approve():
        with factory() as db:
            approval_pid.append(db.scalar(text("select pg_backend_pid()")))
            approval_started.set()
            try:
                approve_payroll_run(run_id, db, db.get(User, ids["admin"]))
            except HTTPException as exc:
                return exc.status_code
            return 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        imported = pool.submit(do_import)
        try:
            assert entered.wait(10)
            approved = pool.submit(do_approve)
            assert approval_started.wait(10)
            deadline = time.monotonic() + 8
            with factory() as observer:
                while time.monotonic() < deadline:
                    waiting = observer.scalar(text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"), {"pid": approval_pid[0]})
                    if waiting:
                        break
                    time.sleep(0.05)
                assert waiting, "Approval did not wait for the import's row lock"
        finally:
            release.set()
        assert imported.result(timeout=15)["created"] == 1
        assert approved.result(timeout=15) == 409
    with factory() as db:
        assert db.get(PayrollRun, run_id).status == "DRAFT"


def test_postgres_parallel_runs_keep_independent_snapshots(pg, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, ids = pg
    with factory.begin() as db:
        run_ids = [_run(db, ids, "parallel-a").id, _run(db, ids, "parallel-b").id]
    barrier = Barrier(2, timeout=10)
    original = calculation._snapshot_ruleset

    def synchronized(*args, **kwargs):
        barrier.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(calculation, "_snapshot_ruleset", synchronized)

    def calculate(run_id: int):
        with factory() as db:
            response = calculation.calculate_payroll_run(db, db.get(PayrollRun, run_id))
            db.commit()
            return response

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(calculate, run_id) for run_id in run_ids]
        responses = [future.result(timeout=20) for future in futures]
    assert all(response["status"] == "CALCULATED" for response in responses)
    with factory() as db:
        runs = [db.get(PayrollRun, run_id) for run_id in run_ids]
        assert runs[0].ruleset_id != runs[1].ruleset_id
        for run in runs:
            snapshot = db.get(Ruleset, run.ruleset_id)
            assert snapshot.code == f"payroll-run-{run.id}"
            assert snapshot.rules["run_id"] == run.id
