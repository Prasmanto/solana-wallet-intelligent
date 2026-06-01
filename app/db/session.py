"""Database session — legacy compatibility layer.

This module is kept for backward compatibility with existing imports.
New code should use infrastructure.database.manager.DatabaseManager
and api.deps.get_db instead.
"""

from app.infrastructure.database.base import Base
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.database.session import get_db, async_session_factory

__all__ = ["Base", "DatabaseManager", "get_db", "async_session_factory"]
