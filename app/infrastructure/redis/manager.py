"""Redis connection manager.

Provides lifecycle-managed Redis pools for:
- General purpose (DB 0)
- Event streams (DB 1)
- Cache (DB 2)

All pools are created during app startup and closed during shutdown.
"""

from __future__ import annotations

from typing import Any

import structlog
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class RedisManager:
    """Manages multiple Redis connection pools tied to app lifespan."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pools: dict[str, ConnectionPool] = {}
        self._clients: dict[str, Redis] = {}

    async def connect(self) -> None:
        """Create connection pools and verify connectivity."""
        pool_configs = {
            "default": (self._settings.REDIS_URL, self._settings.REDIS_DB),
            "streams": (self._settings.REDIS_STREAMS_URL, self._settings.REDIS_STREAMS_DB),
            "cache": (self._settings.REDIS_CACHE_URL, self._settings.REDIS_CACHE_DB),
        }

        for name, (url, db) in pool_configs.items():
            pool = ConnectionPool.from_url(
                url,
                max_connections=20,
                decode_responses=True,
            )
            client = Redis(connection_pool=pool)

            try:
                await client.ping()
                logger.info("redis.pool.connected", pool=name, db=db)
            except Exception as e:
                logger.error("redis.pool.failed", pool=name, error=str(e))
                await client.close()
                raise

            self._pools[name] = pool
            self._clients[name] = client

    async def close(self) -> None:
        """Close all connection pools."""
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("redis.pool.closed", pool=name)
            except Exception as e:
                logger.warning("redis.pool.close_error", pool=name, error=str(e))
        self._clients.clear()
        self._pools.clear()

    def get_client(self, name: str = "default") -> Redis:
        """Get a Redis client by pool name.

        Raises RuntimeError if called before connect().
        """
        if name not in self._clients:
            available = list(self._clients.keys())
            raise RuntimeError(
                f"Redis pool '{name}' not initialized. Available: {available}"
            )
        return self._clients[name]

    async def health_check(self) -> dict[str, Any]:
        """Check health of all pools."""
        results = {}
        for name, client in self._clients.items():
            try:
                info = await client.info("memory")
                results[name] = {
                    "status": "healthy",
                    "used_memory_human": info.get("used_memory_human", "unknown"),
                }
            except Exception as e:
                results[name] = {"status": "unhealthy", "error": str(e)}
        return results
