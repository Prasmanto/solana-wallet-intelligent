"""Pricing refresh worker — periodically refreshes token prices.

Runs as a background task:
1. Fetches all tokens with active positions
2. Refreshes prices from Jupiter API
3. Updates position valuations
4. Detects stale/illiquid tokens

Schedule: Every 5 minutes
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.pricing_service import PricingService
from app.analytics.unrealized_pnl import UnrealizedPnLEngine
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.infrastructure.database.session import async_session_factory
from app.infrastructure.external.jupiter_client import JupiterPriceClient
from app.infrastructure.redis.price_cache import TokenPriceCache
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)

# Refresh interval
REFRESH_INTERVAL_SECONDS = 300  # 5 minutes


class PricingRefreshWorker:
    """Periodically refreshes token prices and updates valuations."""

    def __init__(self) -> None:
        self._running = False
        self._jupiter: JupiterPriceClient | None = None
        self._cache: TokenPriceCache | None = None
        self._pricing: PricingService | None = None
        self._pnl_engine: UnrealizedPnLEngine | None = None

    async def start(self) -> None:
        """Start the pricing refresh worker."""
        from redis.asyncio import Redis
        from app.config import settings

        self._running = True

        # Initialize dependencies
        redis = Redis.from_url(settings.REDIS_CACHE_URL, decode_responses=True)
        self._jupiter = JupiterPriceClient()
        self._cache = TokenPriceCache(redis)
        self._pricing = PricingService(self._jupiter, self._cache)
        self._pnl_engine = UnrealizedPnLEngine(self._pricing)

        logger.info("pricing_worker.started")

        try:
            while self._running:
                await self._refresh_cycle()
                await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("pricing_worker.cancelled")
        finally:
            self._running = False
            await self._jupiter.close()
            await redis.aclose()
            logger.info("pricing_worker.stopped")

    async def stop(self) -> None:
        """Stop the pricing refresh worker."""
        self._running = False

    async def _refresh_cycle(self) -> None:
        """Run a single refresh cycle."""
        start_time = time.time()
        logger.info("pricing_worker.refresh_started")

        try:
            # Get all tokens with active positions
            tokens = await self._get_active_tokens()
            if not tokens:
                logger.info("pricing_worker.no_active_tokens")
                return

            # Refresh prices
            result = await self._pricing.refresh_prices(tokens)

            logger.info(
                "pricing_worker.refresh_completed",
                tokens=len(tokens),
                fetched=result.prices_fetched,
                missing=result.prices_missing,
                duration_ms=result.duration_ms,
            )

        except Exception as e:
            logger.error("pricing_worker.refresh_error", error=str(e))

        duration = (time.time() - start_time) * 1000
        logger.info("pricing_worker.cycle_complete", duration_ms=duration)

    async def _get_active_tokens(self) -> list[str]:
        """Get all token mints with active positions."""
        async with async_session_factory() as session:
            stmt = (
                select(WalletPosition.token_mint)
                .where(WalletPosition.position_size > 0)
                .distinct()
            )
            result = await session.execute(stmt)
            return [row[0] for row in result]
