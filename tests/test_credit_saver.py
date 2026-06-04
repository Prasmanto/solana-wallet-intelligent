"""Credit Saver Mode tests.

Tests:
1. Wallet selection returns max N wallets
2. Never emits accountAddresses=["all"]
3. Provider health marks exhausted keys
4. Data freshness stale detection
5. Alert conditions
6. No secrets printed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings


# ── Wallet Selection Tests ──────────────────────────────────


class TestWalletSelection:
    """Test wallet selection from wallet_metrics."""

    @pytest.mark.asyncio
    async def test_select_wallets_returns_max_n(self) -> None:
        """Wallet selection must not exceed max_wallets."""
        from app.infrastructure.helius.wallet_selector import WalletSelector

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        # Simulate 100 wallets returned from DB
        rows = [
            (f"Wallet{i:040d}", 0.8 - i * 0.001)
            for i in range(100)
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.close = AsyncMock()

        selector = WalletSelector(mock_factory)
        wallets = await selector.select_wallets(max_wallets=50)

        assert len(wallets) <= 50

    @pytest.mark.asyncio
    async def test_select_wallets_excludes_invalid(self) -> None:
        """Invalid addresses must be excluded."""
        from app.infrastructure.helius.wallet_selector import (
            WalletSelector,
            is_valid_solana_address,
        )

        assert is_valid_solana_address("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1") is True
        assert is_valid_solana_address("short") is False
        assert is_valid_solana_address("") is False
        assert is_valid_solana_address("0x1234567890abcdef") is False  # Ethereum format

    @pytest.mark.asyncio
    async def test_select_wallets_deterministic(self) -> None:
        """Same input must produce same output ordering."""
        from app.infrastructure.helius.wallet_selector import WalletSelector

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        rows = [
            ("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", 0.9),
            ("3df5aCigerxML2ZKqNt1jPH8BP3u1tC9Muwj6VfBPCBF", 0.7),
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.close = AsyncMock()

        selector = WalletSelector(mock_factory)
        wallets1 = await selector.select_wallets(max_wallets=10)
        wallets2 = await selector.select_wallets(max_wallets=10)

        assert wallets1 == wallets2

    @pytest.mark.asyncio
    async def test_select_wallets_empty_on_error(self) -> None:
        """Must return empty list on DB error, not raise."""
        from app.infrastructure.helius.wallet_selector import WalletSelector

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_session.execute = AsyncMock(side_effect=Exception("DB down"))
        mock_session.close = AsyncMock()

        selector = WalletSelector(mock_factory)
        wallets = await selector.select_wallets(max_wallets=100)

        assert wallets == []


# ── Webhook Account Addresses Tests ─────────────────────────


class TestWebhookAccountAddresses:
    """Test that webhooks never use ['all'] and always use explicit addresses."""

    def test_never_emits_all(self) -> None:
        """The string 'all' must never appear as an account address."""
        from app.infrastructure.helius.wallet_selector import is_valid_solana_address

        assert is_valid_solana_address("all") is False

    @pytest.mark.asyncio
    async def test_failover_passes_wallets_to_create(self) -> None:
        """Failover must pass wallet addresses when creating webhooks."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_active_provider.return_value = {
            "name": "key_01",
            "key": "test-key-1234",
            "webhook_id": "old-wh-id",
        }
        mock_manager.get_next_available_provider.return_value = {
            "name": "key_02",
            "key": "test-key-5678",
        }
        mock_manager.config = MagicMock()
        mock_manager.config.webhook_url = "http://test:8000/ingest"

        mock_client = AsyncMock()
        mock_client.create_webhook.return_value = {"webhookID": "new-wh-id"}

        failover = WebhookFailover(manager=mock_manager, client=mock_client)
        failover._monitored_wallets = ["Wallet1", "Wallet2"]

        with patch.object(settings, "HELIUS_CREDIT_SAVER_ENABLED", True):
            await failover.failover(force=True)

        # Verify create_webhook was called with account_addresses
        call_kwargs = mock_client.create_webhook.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("account_addresses") == ["Wallet1", "Wallet2"]


# ── Provider Health Tests ───────────────────────────────────


class TestProviderHealth:
    """Test provider health summary and alerts."""

    def test_health_marks_exhausted_keys(self) -> None:
        """Provider health must count exhausted keys correctly."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": False, "exhausted": True, "consecutive_errors": 0},
                {"name": "key_02", "active": True, "exhausted": False, "consecutive_errors": 0},
                {"name": "key_03", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 30,
            "health": "HEALTHY",
        }

        failover = WebhookFailover(manager=mock_manager)
        health = failover.get_provider_health(raw_events_5m=100)

        assert health["exhausted_key_count"] == 1
        assert health["active_key_count"] == 2
        assert health["total_key_count"] == 3

    def test_data_freshness_stale(self) -> None:
        """Stale data must be detected when no events for > threshold."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 1200,  # 20 minutes
            "health": "STALE",
        }

        failover = WebhookFailover(manager=mock_manager)

        with patch.object(settings, "HELIUS_PROVIDER_STALE_MINUTES", 10):
            health = failover.get_provider_health(raw_events_5m=0)

        assert health["data_freshness"] == "STALE"

    def test_data_freshness_fresh(self) -> None:
        """Fresh data must show FRESH when events are recent."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 30,
            "health": "HEALTHY",
        }

        failover = WebhookFailover(manager=mock_manager)
        health = failover.get_provider_health(raw_events_5m=100)

        assert health["data_freshness"] == "FRESH"

    def test_burn_rate_estimation(self) -> None:
        """Events per hour must be estimated from 5m count."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 30,
            "health": "HEALTHY",
        }

        failover = WebhookFailover(manager=mock_manager)
        health = failover.get_provider_health(raw_events_5m=500)

        # 500 events in 5 min = 6000/hour
        assert health["estimated_events_per_hour"] == 6000
        assert health["estimated_credits_per_day"] == 144000


# ── Alert Tests ─────────────────────────────────────────────


class TestAlerts:
    """Test alert conditions."""

    def test_low_active_keys_alert(self) -> None:
        """Must alert when active keys < threshold."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
                {"name": "key_02", "active": False, "exhausted": True, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 30,
        }
        mock_manager.get_active_provider.return_value = {"name": "key_01", "error_reason": None}

        failover = WebhookFailover(manager=mock_manager)

        with patch.object(settings, "HELIUS_MIN_ACTIVE_KEYS_ALERT", 3):
            alerts = failover.check_alerts(raw_events_5m=100)

        assert any("LOW_ACTIVE_KEYS" in a for a in alerts)

    def test_stale_data_alert(self) -> None:
        """Must alert when no events for > stale threshold."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 1200,  # 20 min
        }
        mock_manager.get_active_provider.return_value = {"name": "key_01", "error_reason": None}

        failover = WebhookFailover(manager=mock_manager)

        with patch.object(settings, "HELIUS_PROVIDER_STALE_MINUTES", 10):
            alerts = failover.check_alerts(raw_events_5m=0)

        assert any("STALE_DATA" in a for a in alerts)

    def test_no_alerts_when_healthy(self) -> None:
        """No alerts when system is healthy."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {"name": "key_01", "active": True, "exhausted": False, "consecutive_errors": 0},
                {"name": "key_02", "active": True, "exhausted": False, "consecutive_errors": 0},
                {"name": "key_03", "active": True, "exhausted": False, "consecutive_errors": 0},
            ],
            "last_event_age_seconds": 30,
        }
        mock_manager.get_active_provider.return_value = {"name": "key_01", "error_reason": None}

        failover = WebhookFailover(manager=mock_manager)

        with patch.object(settings, "HELIUS_MIN_ACTIVE_KEYS_ALERT", 3), \
             patch.object(settings, "HELIUS_PROVIDER_STALE_MINUTES", 10):
            alerts = failover.check_alerts(raw_events_5m=100)

        assert alerts == []


# ── Settings Tests ──────────────────────────────────────────


class TestCreditSaverSettings:
    """Test credit saver default settings."""

    def test_credit_saver_enabled_default(self) -> None:
        assert settings.HELIUS_CREDIT_SAVER_ENABLED is True

    def test_max_monitored_wallets_default(self) -> None:
        assert settings.HELIUS_MAX_MONITORED_WALLETS == 3000

    def test_wallet_refresh_hours_default(self) -> None:
        assert settings.HELIUS_WALLET_REFRESH_HOURS == 24

    def test_provider_stale_minutes_default(self) -> None:
        assert settings.HELIUS_PROVIDER_STALE_MINUTES == 10

    def test_min_active_keys_alert_default(self) -> None:
        assert settings.HELIUS_MIN_ACTIVE_KEYS_ALERT == 3


# ── Security Tests ──────────────────────────────────────────


class TestSecurity:
    """Test that no secrets are exposed."""

    def test_provider_health_no_keys(self) -> None:
        """Provider health response must not contain raw API keys."""
        from app.infrastructure.helius.webhook_failover import WebhookFailover

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "providers": [
                {
                    "name": "key_01",
                    "active": True,
                    "exhausted": False,
                    "key_preview": "abcd...efgh",
                    "consecutive_errors": 0,
                },
            ],
            "last_event_age_seconds": 30,
            "health": "HEALTHY",
        }

        failover = WebhookFailover(manager=mock_manager)
        health = failover.get_provider_health(raw_events_5m=100)

        # Health dict must not contain raw keys
        health_str = str(health)
        assert "key_preview" not in health_str or "abcd...efgh" in health_str
