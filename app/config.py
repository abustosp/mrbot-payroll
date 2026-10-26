from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYROLL_", env_file=".env", extra="ignore")

    app_name: str = "Payroll Argentina"
    environment: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///./data/payroll.db"
    session_cookie: str = "payroll_session"
    admin_email: str = "admin@example.com"
    admin_password: str = "admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_sqlite_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    database_path = database_url.removeprefix("sqlite:///")
    if database_path != ":memory:":
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

