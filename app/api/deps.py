"""Dependency injection container.

Provides FastAPI dependencies for database sessions, Redis clients,
and service instances. All dependencies are resolved from the
application state (set during lifespan startup).
"""

from __future__ import annotations

from typing import AsyncIterator

import structlog
from fastapi import Depends, Request
from redis.asyncio import Redis

from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.database.session import Base, async_session_factory
from app.infrastructure.redis.manager import RedisManager

logger = structlog.get_logger(__name__)


# ─── Database Dependencies ──────────────────────────────────


async def get_db(request: Request) -> AsyncIterator:
    """Yield an async database session from the app-managed factory.

    Usage in endpoints:
        @router.get("/")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    db_manager: DatabaseManager = request.app.state.db_manager
    session = db_manager.get_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ─── Redis Dependencies ─────────────────────────────────────


def get_redis(request: Request) -> Redis:
    """Get the default Redis client.

    Usage in endpoints:
        @router.get("/")
        async def cache_check(redis: Redis = Depends(get_redis)):
            ...
    """
    redis_manager: RedisManager = request.app.state.redis_manager
    return redis_manager.get_client("default")


def get_redis_streams(request: Request) -> Redis:
    """Get the Redis Streams client (DB 1)."""
    redis_manager: RedisManager = request.app.state.redis_manager
    return redis_manager.get_client("streams")


def get_redis_cache(request: Request) -> Redis:
    """Get the Redis Cache client (DB 2)."""
    redis_manager: RedisManager = request.app.state.redis_manager
    return redis_manager.get_client("cache")
