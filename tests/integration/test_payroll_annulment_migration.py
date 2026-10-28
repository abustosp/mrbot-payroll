from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.config import get_settings


def test_annulment_migration_preserves_results_and_rejects_lossy_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{tmp_path / 'annulment.sqlite'}"
    monkeypatch.setenv("PAYROLL_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    engine = create_engine(url)
    try:
        command.upgrade(config, "i1a2b3c4d5e6")
        with engine.begin() as db:
            db.execute(text("INSERT INTO organizations (id,name,slug,created_at) VALUES (1,'O','o','2026-01-01')"))
            db.execute(text("INSERT INTO users (id,organization_id,email,password_hash,role,active,created_at) VALUES (1,1,'a','x','admin',1,'2026-01-01')"))
            db.execute(text("INSERT INTO companies (id,organization_id,cuit,legal_name,active,created_at) VALUES (1,1,'1','C',1,'2026-01-01')"))
            db.execute(text("INSERT INTO employees (id,organization_id,employee_code,first_name,last_name,active) VALUES (1,1,'E','A','B',1)"))
            db.execute(text("INSERT INTO payroll_runs (id,organization_id,company_id,code,period_start,period_end,run_type,status,created_by,created_at) VALUES (1,1,1,'R','2026-06-01','2026-06-30','MONTHLY','APPROVED',1,'2026-01-01')"))
            db.execute(text("INSERT INTO payroll_results (id,payroll_run_id,employee_id,remunerative,non_remunerative,deductions,contributions,gross,net,employer_cost) VALUES (1,1,1,100,0,0,0,100,100,100)"))
        command.upgrade(config, "j1a2b3c4d5e6")
        with engine.begin() as db:
            assert db.scalar(text("SELECT net FROM payroll_results WHERE id=1")) == 100
            db.execute(text("UPDATE payroll_runs SET status='ANNULLED', annulled_reason='error', annulled_by=1 WHERE id=1"))
        with pytest.raises(ValueError, match="revertir"):
            command.downgrade(config, "i1a2b3c4d5e6")
        with engine.connect() as db:
            assert db.scalar(text("SELECT net FROM payroll_results WHERE id=1")) == 100
    finally:
        engine.dispose()
        get_settings.cache_clear()
