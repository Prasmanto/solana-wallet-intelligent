"""Database connection manager.

Lifecycle-managed SQLAlchemy async engine and session factory.
Replaces module-level engine creation with startup/shutdown lifecycle.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages async SQLAlchemy engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = None
        self._session_factory = None

    async def connect(self) -> None:
        """Create engine and verify connectivity."""
        pool_size = 20 if self._settings.APP_ENV == "production" else 5
        max_overflow = 10 if self._settings.APP_ENV == "production" else 5

        self._engine = create_async_engine(
            self._settings.DATABASE_URL,
            echo=self._settings.DEBUG,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=30,
        )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Verify connectivity
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()

        url = make_url(self._settings.DATABASE_URL)
        logger.info(
            "database.connected",
            host=url.host,
            port=url.port,
            database=url.database,
            pool_size=pool_size,
        )

    async def close(self) -> None:
        """Dispose engine and close all connections."""
        if self._engine:
            await self._engine.dispose()
            logger.info("database.disposed")

    def get_session(self) -> AsyncSession:
        """Create a new async session.

        Raises RuntimeError if called before connect().
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")
        return self._session_factory()

    async def health_check(self) -> dict[str, Any]:
        """Verify database is reachable and return pool stats."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            pool = self._engine.pool
            return {
                "status": "healthy",
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
