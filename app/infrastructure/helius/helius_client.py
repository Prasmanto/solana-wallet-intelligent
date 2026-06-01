"""Helius Webhooks API client.

Provides async HTTP methods to create, list, update, and delete
Helius webhooks. No secrets are logged. All responses are validated.

API Reference: https://docs.helius.dev/webhooks-and-websockets/webhooks
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

HELIUS_BASE_URL = "https://api.helius.xyz/v0"

# Default monitored programs (same as production webhook)
DEFAULT_MONITORED_PROGRAMS = [
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM V4
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
]

# Helius webhook transaction types
DEFAULT_TRANSACTION_TYPES = ["SWAP"]

# Helius webhook encoding
DEFAULT_ENCODING = "jsonParsed"


class HeliusApiError(Exception):
    """Raised when Helius API returns a non-2xx response."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class HeliusWebhookClient:
    """Async HTTP client for Helius Webhooks API."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "SolanaWalletIntel/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        api_key: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated request to Helius API."""
        client = await self._get_client()

        url = f"{HELIUS_BASE_URL}{path}"
        if params is None:
            params = {}
        params["api-key"] = api_key

        try:
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=json_data)
            elif method == "PUT":
                response = await client.put(url, params=params, json=json_data)
            elif method == "DELETE":
                response = await client.delete(url, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 429:
                raise HeliusApiError(
                    "Rate limited by Helius API",
                    status_code=429,
                    response_body=response.text,
                )

            if response.status_code == 402:
                raise HeliusApiError(
                    "Credit limit exhausted",
                    status_code=402,
                    response_body=response.text,
                )

            if response.status_code >= 400:
                raise HeliusApiError(
                    f"Helius API error: {response.status_code}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            return response.json()

        except httpx.HTTPError as e:
            raise HeliusApiError(f"HTTP error: {e}") from e

    async def list_webhooks(self, api_key: str) -> list[dict[str, Any]]:
        """List all webhooks for the given API key."""
        result = await self._request("GET", "/webhooks", api_key=api_key)
        if isinstance(result, list):
            return result
        return result.get("data", [])

    async def get_webhook(
        self,
        api_key: str,
        webhook_id: str,
    ) -> dict[str, Any] | None:
        """Get a specific webhook by ID."""
        try:
            return await self._request(
                "GET",
                f"/webhooks/{webhook_id}",
                api_key=api_key,
            )
        except HeliusApiError as e:
            if e.status_code == 404:
                return None
            raise

    async def create_webhook(
        self,
        api_key: str,
        webhook_url: str,
        transaction_types: list[str] | None = None,
        account_addresses: list[str] | None = None,
        webhook_type: str = "enhanced",
        encoding: str | None = None,
        txn_status: str = "success",
        auth_header: str | None = None,
        monitored_programs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new Helius webhook.

        Returns the created webhook dict with webhookID.
        """
        payload: dict[str, Any] = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or DEFAULT_TRANSACTION_TYPES,
            "webhookType": webhook_type,
            "txnStatus": txn_status,
        }

        if account_addresses:
            payload["accountAddresses"] = account_addresses

        if encoding:
            payload["encoding"] = encoding

        if auth_header:
            payload["authHeader"] = auth_header

        result = await self._request("POST", "/webhooks", api_key=api_key, json_data=payload)

        logger.info(
            "helius.webhook_created",
            webhook_id=result.get("webhookID", "unknown"),
        )
        return result

    async def update_webhook(
        self,
        api_key: str,
        webhook_id: str,
        webhook_url: str | None = None,
        transaction_types: list[str] | None = None,
        account_addresses: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing webhook."""
        payload: dict[str, Any] = {}
        if webhook_url:
            payload["webhookURL"] = webhook_url
        if transaction_types:
            payload["transactionTypes"] = transaction_types
        if account_addresses:
            payload["accountAddresses"] = account_addresses

        result = await self._request(
            "PUT",
            f"/webhooks/{webhook_id}",
            api_key=api_key,
            json_data=payload,
        )

        logger.info(
            "helius.webhook_updated",
            webhook_id=webhook_id,
        )
        return result

    async def delete_webhook(
        self,
        api_key: str,
        webhook_id: str,
    ) -> bool:
        """Delete a webhook. Returns True if successful."""
        try:
            await self._request(
                "DELETE",
                f"/webhooks/{webhook_id}",
                api_key=api_key,
            )
            logger.info("helius.webhook_deleted", webhook_id=webhook_id)
            return True
        except HeliusApiError as e:
            if e.status_code == 404:
                return True
            logger.error(
                "helius.webhook_delete_failed",
                webhook_id=webhook_id,
                error=str(e),
            )
            return False
