"""Database package; importing models registers all tables with ``Base``."""

from app.database import models as models
from app.database.base import Base

__all__ = ["Base", "models"]

