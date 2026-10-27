from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-in-production"


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
    cors_origins: list[str] = Field(default_factory=list)
    cookie_secure: bool = False
    session_max_age: int = 28800
    web_data_source: Literal["demo", "sql"] = "demo"
    web_auth_enabled: bool = True
    normative_cct_dir: Path = Path("normative/cct")

    @model_validator(mode="after")
    def _require_production_secret(self) -> "Settings":
        # Fuera de development, un secreto vacio o igual al ejemplo deja las
        # sesiones firmadas triviales de forjar: fallar al arrancar (B-16).
        if self.environment.strip().lower() != "development" and (
            not self.secret_key.strip() or self.secret_key == DEFAULT_SECRET_KEY
        ):
            raise ValueError(
                "PAYROLL_SECRET_KEY debe definirse con un valor propio cuando "
                "PAYROLL_ENVIRONMENT no es 'development'."
            )
        # V2-11/PW-6: fuera de development la cookie de sesion debe viajar con
        # Secure; forzarla aunque el operador la haya dejado en false.
        if self.environment.strip().lower() != "development" and not self.cookie_secure:
            self.cookie_secure = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_sqlite_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    database_path = database_url.removeprefix("sqlite:///")
    if database_path != ":memory:":
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
