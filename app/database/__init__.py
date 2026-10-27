"""Database package; importing models registers all tables with ``Base``."""

from app.database import guards as guards
from app.database import models as models
from app.database.base import Base

guards.register_guards()

__all__ = ["Base", "guards", "models"]

