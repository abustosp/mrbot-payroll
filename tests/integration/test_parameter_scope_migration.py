from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.config import get_settings


def test_parameter_scope_migration_preserves_data_and_refuses_lossy_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{tmp_path / 'parameters.sqlite'}"
    monkeypatch.setenv("PAYROLL_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    engine = create_engine(url)
    try:
        command.upgrade(config, "g8a1b2c3d4e5")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO normative_parameters "
                "(jurisdiction, code, value, valid_from, version) "
                "VALUES ('AR', 'rate', 0.01, '2026-01-01', 1)"
            ))
        command.upgrade(config, "h9a1b2c3d4e5")
        with engine.begin() as connection:
            row = connection.execute(text("SELECT value, agreement_code, category_code FROM normative_parameters")).one()
            assert row == (0.01, "", "")
        command.downgrade(config, "g8a1b2c3d4e5")
        assert "agreement_code" not in {column["name"] for column in inspect(engine).get_columns("normative_parameters")}
        command.upgrade(config, "h9a1b2c3d4e5")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO normative_parameters "
                "(jurisdiction, code, agreement_code, category_code, value, valid_from, version) "
                "VALUES ('AR', 'rate', '130/75', '', 0.02, '2026-01-01', 1)"
            ))
        with pytest.raises(ValueError, match="Consolidar parámetros"):
            command.downgrade(config, "g8a1b2c3d4e5")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM normative_parameters")) == 2
    finally:
        engine.dispose()
        get_settings.cache_clear()
