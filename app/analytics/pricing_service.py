"""Pricing service — orchestrates token pricing and valuation.

Responsibilities:
- Fetch prices from Jupiter API
- Cache prices in Redis
- Detect stale prices
- Provide batch pricing
- Handle illiquid tokens

Design:
- Multi-layer caching (memory + Redis)
- Graceful degradation on API failures
- Stale price detection and fallback
- High-throughput batch operations
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from app.infrastructure.external.jupiter_client import JupiterPriceClient
from app.infrastructure.redis.price_cache import TokenPriceCache
from app.schemas.pricing import (
    PriceSnapshot,
    PricingResult,
    TokenPrice,
)

logger = structlog.get_logger(__name__)

# SOL and stablecoins for fallback pricing
SOL_MINT = "So11111111111111111111111111111111111111112"
STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


class PricingService:
    """Service for token pricing and valuation."""

    def __init__(
        self,
        jupiter_client: JupiterPriceClient,
        price_cache: TokenPriceCache,
    ) -> None:
        self._jupiter = jupiter_client
        self._cache = price_cache

    async def get_price(
        self,
        mint: str,
        force_refresh: bool = False,
    ) -> TokenPrice | None:
        """Get current price for a token.

        Args:
            mint: Token mint address
            force_refresh: If True, bypass cache

        Returns:
            TokenPrice or None if unavailable
        """
        # Check cache first (unless forced refresh)
        if not force_refresh:
            cached = await self._cache.get(mint)
            if cached and not cached.is_stale:
                return cached

        # Fetch from Jupiter
        price = await self._jupiter.get_price(mint)
        if price:
            await self._cache.set(mint, price)
            return price

        # Fallback: return stale cached price if available
        cached = await self._cache.get(mint)
        if cached:
            logger.warning(
                "pricing.using_stale",
                mint=mint[:16],
                age_seconds=cached.price_age_seconds,
            )
            return cached

        return None

    async def get_batch_prices(
        self,
        mints: list[str],
        force_refresh: bool = False,
    ) -> dict[str, TokenPrice]:
        """Get prices for multiple tokens.

        Args:
            mints: List of token mint addresses
            force_refresh: If True, bypass cache

        Returns:
            Dict of mint -> TokenPrice
        """
        if not mints:
            return {}

        # Deduplicate
        unique_mints = list(set(mints))

        # Check cache first
        cached: dict[str, TokenPrice] = {}
        to_fetch: list[str] = []

        if not force_refresh:
            cached = await self._cache.get_batch(unique_mints)
            for mint in unique_mints:
                if mint not in cached:
                    to_fetch.append(mint)
                elif cached[mint].is_stale:
                    to_fetch.append(mint)
        else:
            to_fetch = unique_mints

        # Fetch missing/stale prices from Jupiter
        if to_fetch:
            fresh_prices = await self._jupiter.get_batch_prices(to_fetch)
            if fresh_prices:
                await self._cache.set_batch(fresh_prices)
                cached.update(fresh_prices)

        return cached

    async def get_token_info(
        self,
        mint: str,
    ) -> dict[str, Any] | None:
        """Get token metadata from Jupiter."""
        return await self._jupiter.get_token_metadata(mint)

    async def is_price_stale(
        self,
        mint: str,
        threshold_seconds: int = 300,
    ) -> bool:
        """Check if price is stale."""
        age = await self._cache.get_price_age(mint)
        if age is None:
            return True
        return age > threshold_seconds

    async def get_price_confidence(
        self,
        mint: str,
    ) -> Decimal:
        """Get confidence score for a price.

        Confidence decreases with age:
        - Fresh (< 1 min): 1.0
        - Recent (< 5 min): 0.9
        - Stale (< 30 min): 0.7
        - Very stale (> 30 min): 0.3
        """
        age = await self._cache.get_price_age(mint)
        if age is None:
            return Decimal("0")

        if age < 60:
            return Decimal("1.0")
        elif age < 300:
            return Decimal("0.9")
        elif age < 1800:
            return Decimal("0.7")
        else:
            return Decimal("0.3")

    async def refresh_prices(
        self,
        mints: list[str],
    ) -> PricingResult:
        """Refresh prices for a list of tokens.

        Used by the pricing refresh worker.
        """
        start_time = time.time()
        result = PricingResult(success=True)

        try:
            prices = await self.get_batch_prices(mints, force_refresh=True)
            result.prices_fetched = len(prices)

            # Check for missing prices
            for mint in mints:
                if mint not in prices:
                    result.prices_missing += 1

            logger.info(
                "pricing.refresh_completed",
                requested=len(mints),
                fetched=result.prices_fetched,
                missing=result.prices_missing,
            )

        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            logger.error("pricing.refresh_error", error=str(e))

        result.duration_ms = (time.time() - start_time) * 1000
        return result
