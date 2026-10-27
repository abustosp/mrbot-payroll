from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Devuelve ``value`` con zona UTC (V2-23).

    SQLite lee los ``DateTime(timezone=True)`` como ingenuos aunque el
    código escriba aware (``utc_now``). Comparar un aware con un naive
    levanta ``TypeError``; por eso las comparaciones de negocio deben
    hacerse sobre fechas (``.date()``) o normalizar con esta ayuda al
    leer. Los valores naive se asumen UTC (es lo que SQLite persistió).
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
