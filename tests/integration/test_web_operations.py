import re
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.database import Base
from app.database.models import (
    AuditLog,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    PayrollConcept,
    PayrollNovelty,
    PayrollRun,
    PayrollSettlementInput,
)
from app.database.session import get_db
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource
from scripts.seed_demo import seed


def _token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_operations_final_inputs_correction_and_legacy_repair(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'operations.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        demo = seed(db)
        employee = demo["employees"][0]
        employee.termination_date = date(2026, 6, 20)
        for code in ("SUELDO_DIAS", "VACACIONES_NO_GOZADAS", "SAC_PROPORCIONAL"):
            db.add(PayrollConcept(organization_id=demo["organization"].id, code=code, name=code, nature="REMUNERATIVE"))
        for code, nature in (("FINAL_RET", "DEDUCTION"), ("FINAL_CONT", "CONTRIBUTION")):
            db.add(PayrollConcept(organization_id=demo["organization"].id, code=code, name=code, nature=nature))
            formula = FormulaDefinition(organization_id=demo["organization"].id, code=code)
            db.add(formula)
            db.flush()
            db.add(FormulaVersion(formula_id=formula.id, version=1, valid_from=date(2026, 1, 1),
                status="APPROVED", expression={"constant": "0"}, conditions=[{"field": "run_type", "operator": "eq", "value": "FINAL"}]))
        for code, value in (("liq_vacaciones_dias_base", "25"), ("liq_vacaciones_plus_tasa", "0")):
            db.add(NormativeParameter(code=code, value=Decimal(value), valid_from=date(2026, 1, 1)))
        run = PayrollRun(organization_id=demo["organization"].id, company_id=demo["company"].id,
            created_by=demo["admin"].id, code="final-web", run_type="FINAL", status="DRAFT",
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
        db.add(run)
        legacy = PayrollNovelty(organization_id=demo["organization"].id, employee_id=demo["employees"][1].id,
            period="202607", code="LEGACY", kind="AUXILIARY", quantity=Decimal("1"), source="legacy")
        db.add_all([legacy, PayrollNovelty(organization_id=demo["organization"].id,
            employee_id=employee.id, company_id=demo["company"].id, period="202606",
            code="SAC_BASE", kind="AUXILIARY", amount=Decimal("1200000"), source="test")])
        db.flush()
        run_id, employee_id, novelty_id, company_id = run.id, employee.id, legacy.id, demo["company"].id
    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)
    application.dependency_overrides[get_settings] = lambda: Settings(secret_key="operations-test")

    def get_session() -> Generator[Session, None, None]:
        with factory() as db:
            yield db
    application.dependency_overrides[get_db] = get_session
    with TestClient(application) as client:
        csrf = _token(client.get("/login").text)
        client.post("/login", data={"email": "admin@example.com", "password": "admin", "csrf_token": csrf}).raise_for_status()
        page = client.get(f"/liquidaciones/{run_id}/operaciones")
        assert page.status_code == 200 and "other_entitlements_reviewed" in page.text
        csrf = _token(page.text)
        data = {"csrf_token": csrf, "employee_id": employee_id, "cause": "RENUNCIA", "worked_days": "20",
            "worked_base_salary": "1200000", "vacation_days": "5", "vacation_base_salary": "1200000",
            "sac_excluded_days": "0", "other_entitlements_reviewed": "true"}
        path = f"/liquidaciones/{run_id}/operaciones/inputs"
        assert client.post(path, data={**data, "csrf_token": "invalid"}).status_code == 403
        saved = client.post(path, data=data, follow_redirects=False)
        assert "error=" not in saved.headers["location"], saved.headers["location"]
        with factory() as db:
            values = db.scalar(select(PayrollSettlementInput)).values
            assert values["sac_excluded_days"] == 0 and values["other_entitlements_reviewed"] is True
        action = f"/liquidaciones/{run_id}/accion"
        for command in ("calculate", "approve"):
            response = client.post(action, data={"csrf_token": csrf, "action": command}, follow_redirects=False)
            assert "error=" not in response.headers["location"], response.headers["location"]
        assert client.post(path, data=data, follow_redirects=False).headers["location"].find("error=") >= 0
        replacement = client.post(f"/liquidaciones/{run_id}/operaciones/replace", data={
            "csrf_token": csrf, "reason": "Corrección revisada", "code": "replacement-web"}, follow_redirects=False)
        assert "error=" not in replacement.headers["location"], replacement.headers["location"]
        with factory() as db:
            assert db.get(PayrollRun, run_id).status == "ANNULLED"
            draft = db.scalar(select(PayrollRun).where(PayrollRun.code == "replacement-web"))
            assert draft.adjusts_run_id == run_id and draft.status == "DRAFT"
        repairs = client.get("/novedades/reparar")
        assert repairs.status_code == 200 and "LEGACY" in repairs.text
        repaired = client.post(f"/novedades/{novelty_id}/reparar", data={
            "csrf_token": csrf, "company_id": company_id, "reason": "Asignación verificada"}, follow_redirects=False)
        assert "error=" not in repaired.headers["location"], repaired.headers["location"]
        with factory() as db:
            assert db.get(PayrollNovelty, novelty_id).company_id == company_id
            assert db.scalar(select(AuditLog.id).where(AuditLog.action == "payroll_novelty.company_repaired"))
    engine.dispose()
