"""Token price cache — Redis-based price caching with TTL.

Provides:
- In-memory + Redis layered caching
- Stale price detection
- Price age tracking
- Batch cache operations
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from redis.asyncio import Redis

from app.schemas.pricing import TokenPrice, PriceSnapshot

logger = structlog.get_logger(__name__)

# Cache TTLs
PRICE_TTL_SECONDS = 300  # 5 minutes
STALE_THRESHOLD_SECONDS = 300  # Consider stale after 5 minutes


class TokenPriceCache:
    """Redis-based token price cache."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._prefix = "price"

    def _key(self, mint: str) -> str:
        """Get cache key for a mint."""
        return f"{self._prefix}:{mint}"

    async def get(self, mint: str) -> TokenPrice | None:
        """Get cached price for a token."""
        try:
            key = self._key(mint)
            data = await self._redis.get(key)
            if not data:
                return None

            parsed = json.loads(data)
            return TokenPrice(
                mint=parsed["mint"],
                price=Decimal(parsed["price"]),
                symbol=parsed.get("symbol", ""),
                name=parsed.get("name", ""),
                decimals=parsed.get("decimals", 9),
                confidence=Decimal(str(parsed.get("confidence", 1.0))),
                source=parsed.get("source", "cache"),
                fetched_at=datetime.fromisoformat(parsed["fetched_at"]),
            )
        except Exception as e:
            logger.error("cache.get_error", mint=mint[:16], error=str(e))
            return None

    async def set(
        self,
        mint: str,
        price: TokenPrice,
        ttl: int = PRICE_TTL_SECONDS,
    ) -> None:
        """Set cached price for a token."""
        try:
            key = self._key(mint)
            data = {
                "mint": price.mint,
                "price": str(price.price),
                "symbol": price.symbol,
                "name": price.name,
                "decimals": price.decimals,
                "confidence": str(price.confidence),
                "source": price.source,
                "fetched_at": price.fetched_at.isoformat(),
            }
            await self._redis.setex(key, ttl, json.dumps(data))
        except Exception as e:
            logger.error("cache.set_error", mint=mint[:16], error=str(e))

    async def get_batch(self, mints: list[str]) -> dict[str, TokenPrice]:
        """Get cached prices for multiple tokens."""
        results: dict[str, TokenPrice] = {}

        if not mints:
            return results

        try:
            keys = [self._key(mint) for mint in mints]
            values = await self._redis.mget(keys)

            for mint, value in zip(mints, values):
                if value:
                    parsed = json.loads(value)
                    results[mint] = TokenPrice(
                        mint=parsed["mint"],
                        price=Decimal(parsed["price"]),
                        symbol=parsed.get("symbol", ""),
                        name=parsed.get("name", ""),
                        decimals=parsed.get("decimals", 9),
                        confidence=Decimal(str(parsed.get("confidence", 1.0))),
                        source=parsed.get("source", "cache"),
                        fetched_at=datetime.fromisoformat(parsed["fetched_at"]),
                    )
        except Exception as e:
            logger.error("cache.batch_get_error", error=str(e))

        return results

    async def set_batch(
        self,
        prices: dict[str, TokenPrice],
        ttl: int = PRICE_TTL_SECONDS,
    ) -> None:
        """Set cached prices for multiple tokens."""
        if not prices:
            return

        try:
            pipe = self._redis.pipeline()
            for mint, price in prices.items():
                key = self._key(mint)
                data = {
                    "mint": price.mint,
                    "price": str(price.price),
                    "symbol": price.symbol,
                    "name": price.name,
                    "decimals": price.decimals,
                    "confidence": str(price.confidence),
                    "source": price.source,
                    "fetched_at": price.fetched_at.isoformat(),
                }
                pipe.setex(key, ttl, json.dumps(data))
            await pipe.execute()
        except Exception as e:
            logger.error("cache.batch_set_error", error=str(e))

    async def is_stale(self, mint: str, threshold: int = STALE_THRESHOLD_SECONDS) -> bool:
        """Check if a cached price is stale."""
        try:
            key = self._key(mint)
            ttl = await self._redis.ttl(key)
            # TTL returns -2 if key doesn't exist, -1 if no expiry
            if ttl < 0:
                return True
            # If TTL is less than threshold, consider stale
            return ttl < (PRICE_TTL_SECONDS - threshold)
        except Exception:
            return True

    async def get_price_age(self, mint: str) -> float | None:
        """Get age of cached price in seconds."""
        try:
            key = self._key(mint)
            data = await self._redis.get(key)
            if not data:
                return None

            parsed = json.loads(data)
            fetched_at = datetime.fromisoformat(parsed["fetched_at"])
            age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            return age
        except Exception:
            return None

    async def delete(self, mint: str) -> None:
        """Delete cached price for a token."""
        try:
            key = self._key(mint)
            await self._redis.delete(key)
        except Exception as e:
            logger.error("cache.delete_error", mint=mint[:16], error=str(e))

    async def get_all_cached_mints(self) -> list[str]:
        """Get all cached token mints."""
        try:
            pattern = f"{self._prefix}:*"
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                # Extract mint from key
                mint = key.replace(f"{self._prefix}:", "")
                keys.append(mint)
            return keys
        except Exception as e:
            logger.error("cache.scan_error", error=str(e))
            return []
