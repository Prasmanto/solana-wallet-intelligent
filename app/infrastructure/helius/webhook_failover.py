"""Webhook Failover — automatic provider rotation when webhook stops.

Detects stale webhooks (no events for N minutes) and creates
a new webhook on the next available Helius account.

Credit Saver Mode: selects top-N wallets by quality to reduce
Helius credit consumption while preserving alpha signal quality.

No ingestion pipeline logic is modified.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import settings
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
    3. Create webhook on new provider with selected wallet addresses
    4. Update manager state
    5. Log failover event

    Credit Saver Mode:
    - Selects top-N wallets from wallet_metrics by quality signals
    - Updates existing webhook accountAddresses without recreating
    - Refreshes wallet list on configurable interval
    """

    def __init__(
        self,
        manager: WebhookManager | None = None,
        client: HeliusWebhookClient | None = None,
    ) -> None:
        self._manager = manager or get_webhook_manager()
        self._client = client or HeliusWebhookClient()
        self._failover_history: list[FailoverTrigger] = []
        self._monitored_wallets: list[str] = []
        self._wallets_last_refresh: datetime | None = None
        self._events_at_last_check: int = 0
        self._events_per_hour: float = 0.0

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
            wallet_addrs = await self.get_monitored_wallets()
            webhook_info = await self._client.create_webhook(
                api_key=next_key,
                webhook_url=self._manager.config.webhook_url,
                account_addresses=wallet_addrs if wallet_addrs else None,
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
            wallet_addrs = await self.get_monitored_wallets()
            webhook_info = await self._client.create_webhook(
                api_key=key,
                webhook_url=self._manager.config.webhook_url,
                account_addresses=wallet_addrs if wallet_addrs else None,
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

    # ── Credit Saver: Wallet Management ─────────────────────

    async def get_monitored_wallets(self) -> list[str]:
        """Get current monitored wallet list, refreshing if stale."""
        if not settings.HELIUS_CREDIT_SAVER_ENABLED:
            return self._monitored_wallets

        now = datetime.now(timezone.utc)
        stale = False
        if self._wallets_last_refresh is None:
            stale = True
        else:
            age_hours = (now - self._wallets_last_refresh).total_seconds() / 3600
            if age_hours >= settings.HELIUS_WALLET_REFRESH_HOURS:
                stale = True

        if stale or not self._monitored_wallets:
            await self.refresh_wallet_list()

        return self._monitored_wallets

    async def refresh_wallet_list(self) -> int:
        """Refresh the monitored wallet list from wallet_metrics.

        Returns number of wallets selected.
        """
        from app.infrastructure.helius.wallet_selector import WalletSelector
        from app.infrastructure.database.session import async_session_factory

        try:
            selector = WalletSelector(async_session_factory)
            wallets = await selector.select_wallets(
                max_wallets=settings.HELIUS_MAX_MONITORED_WALLETS,
            )
            if wallets:
                self._monitored_wallets = wallets
                self._wallets_last_refresh = datetime.now(timezone.utc)
                logger.info(
                    "credit_saver.wallets_refreshed",
                    count=len(wallets),
                    max=settings.HELIUS_MAX_MONITORED_WALLETS,
                )
            else:
                logger.warning("credit_saver.wallet_refresh_empty")
            return len(wallets)
        except Exception as e:
            logger.error("credit_saver.wallet_refresh_error", error=str(e)[:200])
            return 0

    async def update_webhook_wallets(self) -> bool:
        """Update the active webhook's accountAddresses without recreating.

        Returns True if update succeeded.
        """
        provider = self._manager.get_provider_with_webhook()
        if not provider:
            logger.warning("credit_saver.no_webhook_to_update")
            return False

        api_key = provider.get("key", "")
        webhook_id = provider.get("webhook_id", "")
        if not api_key or not webhook_id:
            return False

        wallets = await self.get_monitored_wallets()
        if not wallets:
            logger.warning("credit_saver.no_wallets_for_update")
            return False

        try:
            await self._client.update_webhook(
                api_key=api_key,
                webhook_id=webhook_id,
                account_addresses=wallets,
            )
            logger.info(
                "credit_saver.webhook_wallets_updated",
                webhook_id=webhook_id,
                wallet_count=len(wallets),
            )
            return True
        except HeliusApiError as e:
            if e.status_code == 402:
                self._manager.mark_provider_exhausted(
                    provider.get("name", "unknown"),
                    reason="credit_exhausted",
                )
            logger.error(
                "credit_saver.update_webhook_failed",
                error=str(e)[:200],
                status_code=e.status_code,
            )
            return False

    # ── Provider Health ─────────────────────────────────────

    def get_provider_health(self, raw_events_5m: int = 0) -> dict[str, Any]:
        """Get comprehensive provider health summary.

        Args:
            raw_events_5m: raw event count in last 5 minutes (from DB)
        """
        status = self._manager.get_status()
        providers = status.get("providers", [])

        active_count = sum(
            1 for p in providers
            if p.get("active") and not p.get("exhausted")
        )
        exhausted_count = sum(
            1 for p in providers
            if p.get("exhausted")
        )
        failed_count = sum(
            1 for p in providers
            if p.get("consecutive_errors", 0) >= 3
        )

        # Estimate events per hour from 5m count
        events_per_hour = raw_events_5m * 12.0 if raw_events_5m > 0 else 0.0

        # Estimate credits per day (1 credit ≈ 1 event for enhanced webhooks)
        credits_per_day = events_per_hour * 24.0

        # Estimate time to exhaustion
        # Each key has ~100K credits/day on free tier
        remaining_keys = max(active_count, 1)
        daily_capacity = remaining_keys * 100_000
        time_to_exhaust_hours = (
            daily_capacity / credits_per_day * 24
            if credits_per_day > 0
            else float("inf")
        )

        # Data freshness
        last_event_age = status.get("last_event_age_seconds")
        stale_minutes = settings.HELIUS_PROVIDER_STALE_MINUTES
        is_stale = (
            last_event_age is not None
            and last_event_age > stale_minutes * 60
        )

        return {
            "provider_status": "STALE" if is_stale else status.get("health", "unknown"),
            "active_key_count": active_count,
            "exhausted_key_count": exhausted_count,
            "failed_key_count": failed_count,
            "total_key_count": len(providers),
            "monitored_wallet_count": len(self._monitored_wallets),
            "last_raw_event_age_seconds": last_event_age,
            "data_freshness": "STALE" if is_stale else "FRESH",
            "estimated_events_per_hour": round(events_per_hour),
            "estimated_credits_per_day": round(credits_per_day),
            "estimated_time_to_exhaustion_hours": (
                round(time_to_exhaust_hours, 1)
                if time_to_exhaust_hours < 10000
                else "unlimited"
            ),
            "credit_saver_enabled": settings.HELIUS_CREDIT_SAVER_ENABLED,
            "max_monitored_wallets": settings.HELIUS_MAX_MONITORED_WALLETS,
            "wallet_refresh_hours": settings.HELIUS_WALLET_REFRESH_HOURS,
        }

    def check_alerts(self, raw_events_5m: int = 0) -> list[str]:
        """Check for alert conditions and return warning messages."""
        alerts = []
        status = self._manager.get_status()
        providers = status.get("providers", [])

        active_count = sum(
            1 for p in providers
            if p.get("active") and not p.get("exhausted")
        )

        # Alert: active keys below threshold
        if active_count < settings.HELIUS_MIN_ACTIVE_KEYS_ALERT:
            alerts.append(
                f"LOW_ACTIVE_KEYS: {active_count} active keys "
                f"(threshold: {settings.HELIUS_MIN_ACTIVE_KEYS_ALERT})"
            )

        # Alert: stale data
        last_event_age = status.get("last_event_age_seconds")
        stale_threshold = settings.HELIUS_PROVIDER_STALE_MINUTES * 60
        if last_event_age is not None and last_event_age > stale_threshold:
            alerts.append(
                f"STALE_DATA: no events for {round(last_event_age/60)}m "
                f"(threshold: {settings.HELIUS_PROVIDER_STALE_MINUTES}m)"
            )

        # Alert: max usage reached on active key
        active_provider = self._manager.get_active_provider()
        if active_provider and active_provider.get("error_reason") == "credit_exhausted_helius":
            alerts.append("MAX_USAGE_REACHED: active provider credit exhausted")

        for alert in alerts:
            logger.warning("helius_alert", message=alert)

        return alerts

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
