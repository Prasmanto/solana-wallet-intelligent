"""Jupiter Price API client.

Provides async integration with Jupiter Price API V3:
- Batch price fetching (up to 100 tokens per request)
- Single token price
- USD-denominated pricing
- Graceful fallback on errors

API Reference: https://docs.jup.ag/docs/apis/price-api
Endpoint: https://lite-api.jup.ag/price/v3

V3 Response Format:
{
  "<mint>": {
    "usdPrice": 0.999,
    "decimals": 6,
    "liquidity": 435428804.12,
    "priceChange24h": 0.005,
    "blockId": 423684146,
    "createdAt": "2024-06-05T08:55:25.527Z"
  }
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog

from app.config.settings import settings
from app.schemas.pricing import TokenPrice

logger = structlog.get_logger(__name__)

# Known stablecoins for pricing
STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", 6),
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("USDT", 6),
}

# SOL mint
SOL_MINT = "So11111111111111111111111111111111111111112"

# Batch size limit
MAX_BATCH_SIZE = 100


class JupiterPriceClient:
    """Async client for Jupiter Price API V3."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def _base_url(self) -> str:
        """Get base URL from settings (configurable)."""
        return settings.JUPITER_PRICE_BASE_URL

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "SolanaWalletIntel/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_price(self, mint: str) -> TokenPrice | None:
        """Get USD price for a single token.

        Args:
            mint: Token mint address

        Returns:
            TokenPrice or None if not found/illiquid/error
        """
        results = await self.get_batch_prices([mint])
        return results.get(mint)

    async def get_batch_prices(
        self,
        mints: list[str],
    ) -> dict[str, TokenPrice]:
        """Get USD prices for multiple tokens in batch.

        Args:
            mints: List of token mint addresses

        Returns:
            Dict of mint -> TokenPrice (only for tokens with valid prices)
        """
        if not mints:
            return {}

        results: dict[str, TokenPrice] = {}

        # Process in batches
        for i in range(0, len(mints), MAX_BATCH_SIZE):
            batch = mints[i : i + MAX_BATCH_SIZE]
            batch_results = await self._fetch_batch(batch)
            results.update(batch_results)

        return results

    async def _fetch_batch(self, mints: list[str]) -> dict[str, TokenPrice]:
        """Fetch a batch of prices from Jupiter V3."""
        results: dict[str, TokenPrice] = {}

        try:
            client = await self._get_client()
            ids_param = ",".join(mints)

            response = await client.get(
                self._base_url,
                params={"ids": ids_param},
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                logger.warning("jupiter.v3unexpected_response", type=type(data).__name__)
                return results

            for mint in mints:
                if mint not in data:
                    continue
                token_data = data[mint]
                if not isinstance(token_data, dict):
                    continue
                price = self._parse_price(mint, token_data)
                if price:
                    results[mint] = price

        except httpx.TimeoutException:
            logger.warning(
                "jupiter.timeout",
                batch_size=len(mints),
                url=self._base_url,
            )
        except httpx.HTTPStatusError as e:
            logger.warning(
                "jupiter.http_error",
                status=e.response.status_code,
                batch_size=len(mints),
            )
        except Exception as e:
            logger.warning(
                "jupiter.fetch_error",
                batch_size=len(mints),
                error=str(e)[:200],
            )

        return results

    def _parse_price(self, mint: str, data: dict[str, Any]) -> TokenPrice | None:
        """Parse Jupiter V3 price response into TokenPrice.

        V3 format:
        {
            "usdPrice": 0.999,
            "decimals": 6,
            "liquidity": 435428804.12,
            "priceChange24h": 0.005,
            "blockId": 423684146,
            "createdAt": "2024-06-05T08:55:25.527Z"
        }
        """
        try:
            usd_price = data.get("usdPrice")
            if usd_price is None:
                return None

            price = Decimal(str(usd_price))
            if price <= 0:
                return None

            decimals = data.get("decimals", 9)
            if not isinstance(decimals, int):
                decimals = 9

            # Get symbol/name from stablecoins map if available
            symbol = ""
            name = ""
            if mint in STABLECOINS:
                symbol, _ = STABLECOINS[mint]

            return TokenPrice(
                mint=mint,
                price=price,
                symbol=symbol,
                name=name,
                decimals=decimals,
                confidence=Decimal("1.0"),
                source="jupiter_v3",
                fetched_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning(
                "jupiter.parse_error",
                mint=mint[:16],
                error=str(e)[:100],
            )
            return None

    async def get_token_metadata(self, mint: str) -> dict[str, Any] | None:
        """Get token metadata — not available in V3 price API.

        Returns basic info from V3 response if available.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                self._base_url,
                params={"ids": mint},
            )
            response.raise_for_status()
            data = response.json()

            if mint in data and isinstance(data[mint], dict):
                return data[mint]
        except Exception as e:
            logger.warning(
                "jupiter.metadata_error",
                mint=mint[:16],
                error=str(e)[:100],
            )
        return None
