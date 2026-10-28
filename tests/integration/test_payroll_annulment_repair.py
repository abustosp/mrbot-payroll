from collections.abc import Generator
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.database.models import (
    AuditLog,
    Company,
    Employee,
    EmploymentContract,
    Organization,
    PayrollNovelty,
    PayrollResult,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.main import app
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def test_annul_replace_and_repair_legacy_novelty(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        org, company, admin = demo["organization"], demo["company"], demo["admin"]
        employee = db.scalar(select(Employee).where(Employee.employee_code == "E-001"))
        other = Company(organization_id=org.id, cuit="30111111111", legal_name="Otra")
        foreign_org = Organization(name="Ajena", slug="ajena")
        db.add_all([other, foreign_org])
        db.flush()
        foreign = Company(organization_id=foreign_org.id, cuit="30222222222", legal_name="Ajena")
        db.add_all([foreign, EmploymentContract(
            employee_id=employee.id, company_id=other.id, valid_from=date(2026, 1, 1),
        )])
        run = PayrollRun(organization_id=org.id, company_id=company.id, code="approved",
                         period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                         run_type="MONTHLY", status="APPROVED", created_by=admin.id)
        affected = PayrollRun(organization_id=org.id, company_id=other.id, code="calculated",
                              period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                              run_type="MONTHLY", status="CALCULATED", created_by=admin.id,
                              inputs_hash="old", results_hash="old")
        novelty = PayrollNovelty(organization_id=org.id, employee_id=employee.id,
                                 period="202606", code="BONO", kind="REMUNERATIVE", source="import")
        db.add_all([run, affected, novelty])
        db.flush()
        result = PayrollResult(payroll_run_id=run.id, employee_id=employee.id)
        affected_result = PayrollResult(payroll_run_id=affected.id, employee_id=employee.id)
        db.add_all([result, affected_result])
        db.flush()
        run_id, novelty_id, result_id = run.id, novelty.id, result.id
        affected_id, other_id, foreign_id, org_id = affected.id, other.id, foreign.id, org.id

    def get_test_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as client:
            client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "admin"}).raise_for_status()
            repair = f"/api/v1/imports/novelties/{novelty_id}/repair"
            assert client.post(repair, json={"company_id": foreign_id, "reason": "revisado"}).status_code == 422
            assert client.post(repair, json={"company_id": other_id, "reason": "revisado"}).status_code == 409
            assert client.post(f"/api/v1/payroll-runs/{run_id}/annul", json={"reason": " "}).status_code == 422
            # A conflicting replacement code must roll back the annulment too.
            conflict = client.post(f"/api/v1/payroll-runs/{run_id}/replace", json={"code": "calculated", "reason": "Corrección"})
            assert conflict.status_code == 409
            assert client.get(f"/api/v1/payroll-runs/{run_id}").json()["status"] == "APPROVED"
            replacement = client.post(f"/api/v1/payroll-runs/{run_id}/replace", json={"code": "replacement", "reason": "Corrección"})
            assert replacement.status_code == 200, replacement.text
            data = replacement.json()
            assert data["adjusts_run_id"] == run_id and data["status"] == "DRAFT"
            assert data["run_type"] == "MONTHLY" and data["company_id"] == company.id
            assert client.post(f"/api/v1/payroll-runs/{run_id}/replace", json={"code": "replacement", "reason": "Corrección"}).json()["id"] == data["id"]
            assert client.post(f"/api/v1/payroll-runs/{run_id}/replace", json={"code": "otra", "reason": "Corrección"}).status_code == 409
            assert client.post(f"/api/v1/payroll-runs/{run_id}/annul", json={"reason": "otra"}).status_code == 409
            assert client.post(f"/api/v1/payroll-runs/{run_id}/calculate").status_code == 409
            assert client.get(f"/api/v1/payroll-runs/{run_id}/results/export").status_code == 409
            assert client.get(f"/api/v1/exports/receipts/{result_id}/json").status_code == 409
            assert client.post(f"/api/v1/exports/receipts/{result_id}").status_code == 409
            assert client.post(repair, json={"company_id": other_id, "reason": "revisado"}).status_code == 200
            assert client.post(repair, json={"company_id": other_id, "reason": "revisado"}).status_code == 409
        source = SqlAlchemyDataSource(factory, org_id)
        assert source.get_receipt(str(result_id)) is None
        assert all(receipt.id != str(result_id) for receipt in source.list_receipts())
        with factory() as db:
            assert db.get(PayrollRun, run_id).status == "ANNULLED"
            assert db.get(PayrollResult, result_id) is not None
            assert db.get(PayrollRun, affected_id).status == "DRAFT"
            assert db.scalar(select(PayrollResult).where(PayrollResult.payroll_run_id == affected_id)) is None
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "payroll_novelty.company_repaired"))
            assert audit.before == {"company_id": None}
            assert audit.after == {"company_id": other_id, "reason": "revisado"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_repair_collisions_organization_permissions_and_import_policy(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'repair.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        org, company, admin = demo["organization"], demo["company"], demo["admin"]
        employee = db.scalar(select(Employee).where(Employee.employee_code == "E-001"))
        legacy = PayrollNovelty(organization_id=org.id, employee_id=employee.id,
                                period="202606", code="BONO", source="import")
        collision = PayrollNovelty(organization_id=org.id, employee_id=employee.id,
                                   company_id=company.id, period="202606", code="BONO", source="import")
        foreign_org = Organization(name="Ajena", slug="foreign")
        db.add(foreign_org)
        db.flush()
        foreign_employee = Employee(organization_id=foreign_org.id, employee_code="F", first_name="A", last_name="B")
        db.add(foreign_employee)
        db.flush()
        foreign_novelty = PayrollNovelty(organization_id=foreign_org.id, employee_id=foreign_employee.id,
                                        period="202606", code="BONO", source="import")
        run = PayrollRun(organization_id=org.id, company_id=company.id, code="first",
                         period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                         status="APPROVED", created_by=admin.id)
        db.add_all([legacy, collision, foreign_novelty, run])
        db.flush()
        company_id, admin_id, legacy_id, foreign_id, run_id = company.id, admin.id, legacy.id, foreign_novelty.id, run.id

    def get_test_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as client:
            client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "admin"}).raise_for_status()
            url = f"/api/v1/imports/novelties/{legacy_id}/repair"
            body = {"company_id": company_id, "reason": "revisado"}
            assert client.post(f"/api/v1/imports/novelties/{foreign_id}/repair", json=body).status_code == 404
            with factory.begin() as db:
                db.get(User, admin_id).role = "editor"
            assert client.post(url, json=body).status_code == 403
            assert client.post(f"/api/v1/payroll-runs/{run_id}/annul", json={"reason": "error"}).status_code == 403
            with factory.begin() as db:
                db.get(User, admin_id).role = "admin"
            assert client.post(f"/api/v1/payroll-runs/{run_id}/annul", json={"reason": "error"}).status_code == 200
            assert client.post(url, json=body).status_code == 409
            with factory() as db:
                assert db.get(PayrollNovelty, legacy_id).company_id is None
            csv = "Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\nE-001;202606;PREMIO;1;100;ok\n"
            files = {"file": ("nov.csv", csv.encode(), "text/csv")}
            imported = client.post(f"/api/v1/imports/novelties?dry_run=false&company_id={company_id}", files=files)
            assert imported.json()["created"] == 1, imported.text
            with factory.begin() as db:
                db.add(PayrollRun(organization_id=org.id, company_id=company_id, code="other-approved",
                                  period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                                  status="APPROVED", created_by=admin_id))
            csv = csv.replace("PREMIO", "PLUS")
            files = {"file": ("nov.csv", csv.encode(), "text/csv")}
            blocked = client.post(f"/api/v1/imports/novelties?dry_run=false&company_id={company_id}", files=files)
            assert blocked.json()["created"] == 0
            assert blocked.json()["errors"][0]["code"] == "liquidacion_bloqueada"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
