from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.config import get_settings

REVISION = "b7e4c1a92d30"
PREVIOUS_REVISION = "8f3c2a91d4b7"
CREATED_AT = "2026-10-26 12:00:00"


def _insert(connection, table: str, **values: object) -> None:
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def _insert_novelty(connection, **overrides: object) -> None:
    values: dict[str, object] = {
        "id": 1,
        "organization_id": 1,
        "employee_id": 1,
        "period": "202606",
        "code": "horas_extra",
        "kind": "REMUNERATIVE",
        "quantity": "10",
        "unit": "horas",
        "amount": None,
        "description": None,
        "source": "test",
        "external_id": "ext-1",
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    _insert(connection, "payroll_novelties", **values)


def test_novelty_migration_upgrade_and_downgrade_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    get_settings.cache_clear()
    database_path = tmp_path / "novelties-migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("PAYROLL_DATABASE_URL", database_url)
    try:
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("script_location", str(project_root / "alembic"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert len(heads) == 1
        revision = script.get_revision(REVISION)
        assert revision is not None
        assert revision.down_revision == PREVIOUS_REVISION

        command.upgrade(config, REVISION)

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            assert "payroll_novelties" in inspector.get_table_names()
            columns = {
                column["name"]: column for column in inspector.get_columns("payroll_novelties")
            }
            assert set(columns) == {
                "id",
                "organization_id",
                "employee_id",
                "period",
                "code",
                "kind",
                "quantity",
                "unit",
                "amount",
                "description",
                "source",
                "external_id",
                "created_at",
            }
            uniques = {
                tuple(sorted(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints("payroll_novelties")
            }
            assert ("code", "employee_id", "period", "source") in uniques
            assert ("external_id", "organization_id") in uniques

            with engine.begin() as connection:
                _insert(
                    connection,
                    "organizations",
                    id=1,
                    name="Organizacion Test",
                    slug="test",
                    created_at=CREATED_AT,
                )
                _insert(
                    connection,
                    "employees",
                    id=1,
                    organization_id=1,
                    employee_code="E-1",
                    first_name="Test",
                    last_name="Empleado",
                    active=1,
                )
                _insert_novelty(connection)
                _insert_novelty(
                    connection,
                    id=2,
                    code="ausencia",
                    external_id=None,
                )

            with pytest.raises(IntegrityError), engine.begin() as connection:
                _insert_novelty(connection, id=3, period="2026AB")
            with pytest.raises(IntegrityError), engine.begin() as connection:
                _insert_novelty(
                    connection,
                    id=4,
                    code="licencia",
                    kind="NOT_A_KIND",
                )
            with pytest.raises(IntegrityError), engine.begin() as connection:
                _insert_novelty(
                    connection,
                    id=5,
                    code="horas_extra",
                    external_id="ext-2",
                )
            with pytest.raises(IntegrityError), engine.begin() as connection:
                _insert_novelty(
                    connection,
                    id=6,
                    code="comision",
                    external_id="ext-1",
                )

            command.downgrade(config, PREVIOUS_REVISION)
            assert "payroll_novelties" not in inspect(engine).get_table_names()

            command.upgrade(config, "head")
            assert "payroll_novelties" in inspect(engine).get_table_names()

            command.downgrade(config, "base")
            assert "payroll_novelties" not in inspect(engine).get_table_names()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_company_backfill_only_for_unambiguous_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    get_settings.cache_clear()
    database_url = f"sqlite:///{tmp_path / 'company-backfill.db'}"
    monkeypatch.setenv("PAYROLL_DATABASE_URL", database_url)
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "f7a1b2c3d4e5")
        with engine.begin() as connection:
            _insert(
                connection, "organizations", id=1, name="Org", slug="org", created_at=CREATED_AT
            )
            for company_id in (1, 2):
                _insert(
                    connection,
                    "companies",
                    id=company_id,
                    organization_id=1,
                    cuit=f"3000000000{company_id}",
                    legal_name=f"Company {company_id}",
                    active=1,
                    created_at=CREATED_AT,
                )
            for employee_id in (1, 2, 3):
                _insert(
                    connection,
                    "employees",
                    id=employee_id,
                    organization_id=1,
                    employee_code=f"E-{employee_id}",
                    first_name="Test",
                    last_name="Empleado",
                    active=1,
                )
                _insert_novelty(
                    connection,
                    id=employee_id,
                    employee_id=employee_id,
                    external_id=f"ext-{employee_id}",
                )
            for contract_id, employee_id, company_id, start, end in [
                (1, 1, 1, "2026-06-15", "2026-06-30"),
                (2, 2, 1, "2025-01-01", None),
                (3, 2, 2, "2026-06-01", None),
                (4, 3, 1, "2026-07-01", None),
            ]:
                _insert(
                    connection,
                    "employment_contracts",
                    id=contract_id,
                    employee_id=employee_id,
                    company_id=company_id,
                    valid_from=start,
                    valid_to=end,
                    employment_type="full_time",
                    active=1,
                )
        command.upgrade(config, "g8a1b2c3d4e5")
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT id, company_id, external_id FROM payroll_novelties ORDER BY id")
            ).all() == [(1, 1, "ext-1"), (2, None, "ext-2"), (3, None, "ext-3")]
            _insert_novelty(connection, id=4, employee_id=1, company_id=2, external_id="ext-4")
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_novelty(connection, id=5, employee_id=1, company_id=1, external_id="ext-5")
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_novelty(
                connection, id=6, employee_id=1, company_id=2, code="otro", external_id="ext-1"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()
