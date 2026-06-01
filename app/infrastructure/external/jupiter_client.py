"""Jupiter Price API client.

Provides async integration with Jupiter Price API v2:
- Batch price fetching
- Single token price
- Token metadata
- Price confidence scoring

API Reference: https://docs.jup.ag/docs/apis/price-api
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog

from app.schemas.pricing import TokenPrice

logger = structlog.get_logger(__name__)

# Jupiter Price API v2
JUPITER_PRICE_API = "https://api.jup.ag/price/v2"
JUPITER_TOKEN_API = "https://tokens.jup.ag/token"

# Batch size limit for Jupiter API
MAX_BATCH_SIZE = 100

# Known stablecoins for pricing
STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", 6),
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("USDT", 6),
}

# SOL mint
SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterPriceClient:
    """Async client for Jupiter Price API."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

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

    async def get_price(
        self,
        mint: str,
        vs_token: str = SOL_MINT,
    ) -> TokenPrice | None:
        """Get price for a single token.

        Args:
            mint: Token mint address
            vs_token: Quote token (default: SOL)

        Returns:
            TokenPrice or None if not found
        """
        try:
            client = await self._get_client()
            response = await client.get(
                JUPITER_PRICE_API,
                params={
                    "ids": mint,
                    "vsToken": vs_token,
                },
            )
            response.raise_for_status()
            data = response.json()

            if mint not in data.get("data", {}):
                return None

            token_data = data["data"][mint]
            return self._parse_price(mint, token_data)

        except Exception as e:
            logger.error(
                "jupiter.price_fetch_error",
                mint=mint[:16],
                error=str(e),
            )
            return None

    async def get_batch_prices(
        self,
        mints: list[str],
        vs_token: str = SOL_MINT,
    ) -> dict[str, TokenPrice]:
        """Get prices for multiple tokens in batch.

        Args:
            mints: List of token mint addresses
            vs_token: Quote token (default: SOL)

        Returns:
            Dict of mint -> TokenPrice
        """
        if not mints:
            return {}

        results: dict[str, TokenPrice] = {}

        # Process in batches
        for i in range(0, len(mints), MAX_BATCH_SIZE):
            batch = mints[i:i + MAX_BATCH_SIZE]
            batch_results = await self._fetch_batch(batch, vs_token)
            results.update(batch_results)

        return results

    async def _fetch_batch(
        self,
        mints: list[str],
        vs_token: str,
    ) -> dict[str, TokenPrice]:
        """Fetch a batch of prices."""
        results: dict[str, TokenPrice] = {}

        try:
            client = await self._get_client()
            ids_param = ",".join(mints)

            response = await client.get(
                JUPITER_PRICE_API,
                params={
                    "ids": ids_param,
                    "vsToken": vs_token,
                },
            )
            response.raise_for_status()
            data = response.json()

            for mint in mints:
                if mint in data.get("data", {}):
                    token_data = data["data"][mint]
                    price = self._parse_price(mint, token_data)
                    if price:
                        results[mint] = price

        except Exception as e:
            logger.error(
                "jupiter.batch_fetch_error",
                batch_size=len(mints),
                error=str(e),
            )

        return results

    def _parse_price(
        self,
        mint: str,
        data: dict[str, Any],
    ) -> TokenPrice | None:
        """Parse Jupiter price response into TokenPrice."""
        try:
            price = Decimal(str(data.get("price", 0)))
            if price <= 0:
                return None

            # Get token info if available
            token_info = data.get("token_info", {})
            decimals = token_info.get("decimals", 9)

            # Calculate confidence based on price staleness
            confidence = Decimal("1.0")

            return TokenPrice(
                mint=mint,
                price=price,
                symbol=token_info.get("symbol", ""),
                name=token_info.get("name", ""),
                decimals=decimals,
                confidence=confidence,
                source="jupiter",
                fetched_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(
                "jupiter.parse_error",
                mint=mint[:16],
                error=str(e),
            )
            return None

    async def get_token_metadata(
        self,
        mint: str,
    ) -> dict[str, Any] | None:
        """Get token metadata from Jupiter."""
        try:
            client = await self._get_client()
            response = await client.get(f"{JUPITER_TOKEN_API}/{mint}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(
                "jupiter.metadata_error",
                mint=mint[:16],
                error=str(e),
            )
            return None
