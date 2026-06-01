"""Webhook Failover — automatic provider rotation when webhook stops.

Detects stale webhooks (no events for N minutes) and creates
a new webhook on the next available Helius account.

No ingestion pipeline logic is modified.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.infrastructure.helius.helius_client import HeliusApiError, HeliusWebhookClient
from app.infrastructure.helius.webhook_manager import WebhookManager, get_webhook_manager
from app.infrastructure.helius.webhook_models import (
    FailoverTrigger,
    WebhookFailoverConfig,
    WebhookHealthStatus,
)

logger = structlog.get_logger(__name__)


class WebhookFailover:
    """Orchestrates failover across Helius webhook providers.

    Lifecycle:
    1. Check if current webhook is healthy (received events recently)
    2. If stale/exhausted, find next available provider
    3. Create webhook on new provider
    4. Update manager state
    5. Log failover event
    """

    def __init__(
        self,
        manager: WebhookManager | None = None,
        client: HeliusWebhookClient | None = None,
    ) -> None:
        self._manager = manager or get_webhook_manager()
        self._client = client or HeliusWebhookClient()
        self._failover_history: list[FailoverTrigger] = []

    @property
    def manager(self) -> WebhookManager:
        return self._manager

    @property
    def client(self) -> HeliusWebhookClient:
        return self._client

    async def check_health(self) -> WebhookHealthStatus:
        """Check if current webhook is healthy."""
        provider = self._manager.get_provider_with_webhook()
        if not provider:
            return WebhookHealthStatus.NOT_FOUND

        webhook_id = provider.get("webhook_id")
        api_key = provider.get("key", "")
        name = provider.get("name", "unknown")

        if not webhook_id or not api_key:
            return WebhookHealthStatus.NOT_FOUND

        # Check event staleness
        last_event_at = provider.get("last_webhook_event_at")
        if last_event_at:
            age_seconds = time.time() - last_event_at
            if age_seconds > self._manager.config.stale_threshold_seconds:
                logger.warning(
                    "webhook_failover.stale",
                    name=name,
                    age_seconds=round(age_seconds, 1),
                    threshold=self._manager.config.stale_threshold_seconds,
                )
                return WebhookHealthStatus.STALE

        # Verify webhook exists on Helius side
        try:
            webhook_info = await self._client.get_webhook(api_key, webhook_id)
            if webhook_info is None:
                return WebhookHealthStatus.NOT_FOUND
            return WebhookHealthStatus.HEALTHY
        except HeliusApiError as e:
            if e.status_code == 402:
                return WebhookHealthStatus.EXHAUSTED
            if e.status_code == 429:
                return WebhookHealthStatus.RATE_LIMITED
            return WebhookHealthStatus.ERROR

    async def failover(self, force: bool = False) -> FailoverTrigger | None:
        """Execute failover to next available provider.

        Returns FailoverTrigger if failover was performed, None otherwise.
        """
        current = self._manager.get_active_provider()
        current_name = current.get("name", "unknown") if current else "none"

        # Check if failover is needed
        if not force:
            health = await self.check_health()
            if health == WebhookHealthStatus.HEALTHY:
                logger.debug("webhook_failover.healthy", name=current_name)
                return None

        # Find next available provider
        next_provider = self._manager.get_next_available_provider()
        if not next_provider:
            logger.error("webhook_failover.no_providers_available")
            trigger = FailoverTrigger(
                reason="no_available_providers",
                previous_provider=current_name,
                details={"error": "All providers exhausted or inactive"},
            )
            self._failover_history.append(trigger)
            return trigger

        next_name = next_provider.get("name", "unknown")
        next_key = next_provider.get("key", "")

        logger.info(
            "webhook_failover.initiating",
            from_provider=current_name,
            to_provider=next_name,
        )

        # Create webhook on next provider
        try:
            webhook_info = await self._client.create_webhook(
                api_key=next_key,
                webhook_url=self._manager.config.webhook_url,
            )
            new_webhook_id = webhook_info.get("webhookID", "")

            if not new_webhook_id:
                logger.error("webhook_failover.no_webhook_id", response=webhook_info)
                return None

            # Update manager state
            self._manager.set_webhook_id(next_name, new_webhook_id)
            self._manager.set_current_provider(next_name)

            # Mark old provider as exhausted if it had a webhook
            if current and current.get("webhook_id"):
                self._manager.mark_provider_exhausted(
                    current_name,
                    reason="failover_triggered",
                )

            trigger = FailoverTrigger(
                reason="webhook_stale",
                previous_provider=current_name,
                new_provider=next_name,
                details={
                    "new_webhook_id": new_webhook_id,
                    "webhook_url": self._manager.config.webhook_url,
                },
            )
            self._failover_history.append(trigger)

            logger.info(
                "webhook_failover.completed",
                from_provider=current_name,
                to_provider=next_name,
                webhook_id=new_webhook_id,
            )

            return trigger

        except HeliusApiError as e:
            logger.error(
                "webhook_failover.create_failed",
                provider=next_name,
                error=str(e),
                status_code=e.status_code,
            )

            if e.status_code == 402:
                self._manager.mark_provider_exhausted(next_name, reason="credit_exhausted")
            else:
                self._manager.mark_provider_unhealthy(
                    next_name,
                    WebhookHealthStatus.ERROR,
                    error=str(e),
                )

            trigger = FailoverTrigger(
                reason="create_webhook_failed",
                previous_provider=current_name,
                new_provider=next_name,
                details={"error": str(e), "status_code": e.status_code},
            )
            self._failover_history.append(trigger)
            return trigger

    async def create_webhook_for_current(self) -> str | None:
        """Create a webhook for the current active provider.

        Returns webhook_id if successful, None otherwise.
        """
        provider = self._manager.get_active_provider()
        if not provider:
            logger.error("webhook_failover.no_active_provider")
            return None

        name = provider.get("name", "unknown")
        key = provider.get("key", "")

        # Check if already has a webhook
        existing_webhook_id = provider.get("webhook_id")
        if existing_webhook_id:
            logger.info(
                "webhook_failover.webhook_exists",
                name=name,
                webhook_id=existing_webhook_id,
            )
            return existing_webhook_id

        try:
            webhook_info = await self._client.create_webhook(
                api_key=key,
                webhook_url=self._manager.config.webhook_url,
            )
            new_webhook_id = webhook_info.get("webhookID", "")

            if new_webhook_id:
                self._manager.set_webhook_id(name, new_webhook_id)
                logger.info(
                    "webhook_failover.webhook_created",
                    name=name,
                    webhook_id=new_webhook_id,
                )
                return new_webhook_id

        except HeliusApiError as e:
            logger.error(
                "webhook_failover.create_failed",
                provider=name,
                error=str(e),
            )
            if e.status_code == 402:
                self._manager.mark_provider_exhausted(name, reason="credit_exhausted")

        return None

    async def reset_provider_health(self, name: str) -> bool:
        """Reset a provider's health status to active."""
        provider = None
        for p in self._manager.providers:
            if p.get("name") == name:
                provider = p
                break

        if not provider:
            return False

        self._manager.mark_provider_healthy(name)
        return True

    def get_failover_history(self) -> list[dict[str, Any]]:
        """Get recent failover events."""
        return [
            {
                "reason": t.reason,
                "triggered_at": t.triggered_at,
                "previous_provider": t.previous_provider,
                "new_provider": t.new_provider,
                "details": t.details,
            }
            for t in self._failover_history[-20:]
        ]

    async def cleanup(self) -> None:
        """Close HTTP client."""
        await self._client.close()


# ── Singleton ────────────────────────────────────────────────
_failover: WebhookFailover | None = None


def get_webhook_failover() -> WebhookFailover:
    """Get or create the failover singleton."""
    global _failover
    if _failover is None:
        _failover = WebhookFailover()
    return _failover
