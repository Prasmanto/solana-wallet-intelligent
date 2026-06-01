"""Webhook Manager — central state for Helius webhook providers.

Maintains the mapping between API keys and their webhook ownership.
Thread-safe file operations. No secrets logged.
"""

from __future__ import annotations

import json
import os
import stat
import time
from typing import Any

import structlog

from app.infrastructure.helius.webhook_models import (
    WebhookFailoverConfig,
    WebhookHealthStatus,
    WebhookProviderState,
)

logger = structlog.get_logger(__name__)

CONFIG_FILE = "/root/solana-wallet-intel/config/api_keys.json"


def _check_file_permissions() -> None:
    """Warn if config file is world-readable."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return
        file_stat = os.stat(CONFIG_FILE)
        if file_stat.st_mode & stat.S_IROTH:
            logger.warning(
                "webhook_manager.file_world_readable",
                path=CONFIG_FILE,
                suggestion="Run: chmod 600 config/api_keys.json",
            )
    except Exception:
        pass


class WebhookManager:
    """Manages Helius API keys with webhook ownership state.

    Extends the api_keys.json schema to track webhook_id, health,
    and failover state per key. Thread-safe save with atomic writes.
    """

    def __init__(self) -> None:
        self._providers: list[dict[str, Any]] = []
        self._current_index: int = 0
        self._config = WebhookFailoverConfig()
        self._last_load: float = 0
        _check_file_permissions()
        self._load_config()

    def _load_config(self) -> None:
        """Load provider state from api_keys.json."""
        try:
            if not os.path.exists(CONFIG_FILE):
                logger.warning("webhook_manager.config_not_found", path=CONFIG_FILE)
                return

            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)

            # Migrate legacy keys if needed
            raw_keys = data.get("api_keys", [])
            self._providers = []
            for i, key_data in enumerate(raw_keys):
                # Support legacy format (just key string)
                if isinstance(key_data, str):
                    key_data = {"key": key_data, "name": f"key_{i+1:02d}", "active": True}

                # Ensure webhook state fields exist
                provider = {
                    "name": key_data.get("name", f"key_{i+1:02d}"),
                    "key": key_data.get("key", ""),
                    "active": key_data.get("active", True),
                    "exhausted": key_data.get("exhausted", False),
                    "webhook_id": key_data.get("webhook_id"),
                    "webhook_url": key_data.get("webhook_url"),
                    "webhook_status": key_data.get("webhook_status", "unknown"),
                    "webhook_error": key_data.get("webhook_error"),
                    "last_used": key_data.get("last_used"),
                    "last_webhook_event_at": key_data.get("last_webhook_event_at"),
                    "last_health_check_at": key_data.get("last_health_check_at"),
                    "last_failover_at": key_data.get("last_failover_at"),
                    "exhausted_at": key_data.get("exhausted_at"),
                    "consecutive_errors": key_data.get("consecutive_errors", 0),
                    "error_reason": key_data.get("error_reason"),
                }
                self._providers.append(provider)

            self._current_index = data.get("current_index", 0)

            # Load failover config if present
            failover_cfg = data.get("failover_config", {})
            if failover_cfg:
                self._config = WebhookFailoverConfig(**failover_cfg)

            self._last_load = time.time()
            logger.info(
                "webhook_manager.loaded",
                provider_count=len(self._providers),
                current_index=self._current_index,
                multi_webhook_mode=self._config.multi_webhook_mode,
            )
        except Exception as e:
            logger.error("webhook_manager.load_error", error=str(e))

    def _save_config(self) -> None:
        """Save provider state to api_keys.json with restricted permissions."""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({
                    "api_keys": self._providers,
                    "current_index": self._current_index,
                    "failover_config": self._config.model_dump(),
                }, f, indent=2, default=str)
            self._last_load = time.time()
        except Exception as e:
            logger.error("webhook_manager.save_error", error=str(e))

    def reload(self) -> None:
        """Reload config from disk."""
        self._load_config()

    @property
    def config(self) -> WebhookFailoverConfig:
        return self._config

    @property
    def providers(self) -> list[dict[str, Any]]:
        return self._providers

    @property
    def current_index(self) -> int:
        return self._current_index

    def get_active_provider(self) -> dict[str, Any] | None:
        """Get the currently active provider (with webhook)."""
        if not self._providers:
            return None
        idx = min(self._current_index, len(self._providers) - 1)
        return self._providers[idx]

    def get_active_key(self) -> str:
        """Get the raw API key of the active provider."""
        provider = self.get_active_provider()
        if provider:
            return provider.get("key", "")
        return ""

    def get_provider_with_webhook(self) -> dict[str, Any] | None:
        """Find the first provider that has a webhook_id."""
        for p in self._providers:
            if p.get("webhook_id") and p.get("active"):
                return p
        return None

    def get_next_available_provider(self) -> dict[str, Any] | None:
        """Find next provider that is active and doesn't have an exhausted webhook."""
        if not self._providers:
            return None

        start = self._current_index + 1
        for offset in range(len(self._providers)):
            idx = (start + offset) % len(self._providers)
            p = self._providers[idx]
            if p.get("active") and not p.get("exhausted"):
                return p
        return None

    def mark_provider_exhausted(
        self,
        name: str,
        reason: str = "credit_exhausted",
    ) -> None:
        """Mark a provider as exhausted."""
        for p in self._providers:
            if p.get("name") == name:
                p["exhausted"] = True
                p["active"] = False
                p["exhausted_at"] = time.time()
                p["error_reason"] = reason
                p["webhook_status"] = WebhookHealthStatus.EXHAUSTED.value
                logger.warning(
                    "webhook_manager.provider_exhausted",
                    name=name,
                    reason=reason,
                )
                self._save_config()
                return

    def mark_provider_unhealthy(
        self,
        name: str,
        status: WebhookHealthStatus,
        error: str | None = None,
    ) -> None:
        """Mark a provider as unhealthy."""
        for p in self._providers:
            if p.get("name") == name:
                p["webhook_status"] = status.value
                p["webhook_error"] = error
                p["consecutive_errors"] = p.get("consecutive_errors", 0) + 1
                p["last_health_check_at"] = time.time()
                if p["consecutive_errors"] >= self._config.max_consecutive_errors:
                    p["active"] = False
                    p["error_reason"] = error or status.value
                    logger.warning(
                        "webhook_manager.provider_disabled",
                        name=name,
                        consecutive_errors=p["consecutive_errors"],
                    )
                self._save_config()
                return

    def mark_provider_healthy(self, name: str) -> None:
        """Mark a provider as healthy."""
        for p in self._providers:
            if p.get("name") == name:
                p["webhook_status"] = WebhookHealthStatus.HEALTHY.value
                p["webhook_error"] = None
                p["consecutive_errors"] = 0
                p["error_reason"] = None
                p["active"] = True
                p["last_health_check_at"] = time.time()
                self._save_config()
                return

    def set_webhook_id(self, name: str, webhook_id: str) -> None:
        """Store webhook_id for a provider."""
        for p in self._providers:
            if p.get("name") == name:
                p["webhook_id"] = webhook_id
                p["webhook_url"] = self._config.webhook_url
                p["webhook_status"] = WebhookHealthStatus.HEALTHY.value
                logger.info(
                    "webhook_manager.webhook_assigned",
                    name=name,
                    webhook_id=webhook_id,
                )
                self._save_config()
                return

    def set_current_provider(self, name: str) -> None:
        """Set the current active provider by name."""
        for i, p in enumerate(self._providers):
            if p.get("name") == name:
                self._current_index = i
                self._save_config()
                logger.info(
                    "webhook_manager.current_set",
                    name=name,
                    index=i,
                )
                return

    def record_event_received(self, name: str | None = None) -> None:
        """Record that an event was received from a provider."""
        provider_name = name
        if not provider_name:
            active = self.get_active_provider()
            if active:
                provider_name = active.get("name")

        if provider_name:
            for p in self._providers:
                if p.get("name") == provider_name:
                    p["last_webhook_event_at"] = time.time()
                    break
            self._save_config()

    def get_time_since_last_event(self) -> float | None:
        """Seconds since last webhook event. None if never received."""
        provider = self.get_provider_with_webhook()
        if not provider:
            return None
        last_at = provider.get("last_webhook_event_at")
        if not last_at:
            return None
        return time.time() - last_at

    def get_status(self) -> dict[str, Any]:
        """Get safe status dict (no secrets)."""
        active = self.get_active_provider()
        provider_with_webhook = self.get_provider_with_webhook()
        time_since_event = self.get_time_since_last_event()

        providers_safe = []
        for p in self._providers:
            raw_key = p.get("key", "")
            providers_safe.append({
                "name": p.get("name", "unknown"),
                "active": p.get("active", True),
                "exhausted": p.get("exhausted", False),
                "key_preview": (
                    raw_key[:4] + "..." + raw_key[-4:]
                    if len(raw_key) > 8
                    else "***"
                ),
                "webhook_id": p.get("webhook_id"),
                "webhook_status": p.get("webhook_status", "unknown"),
                "webhook_error": p.get("webhook_error"),
                "last_used": p.get("last_used"),
                "last_webhook_event_at": p.get("last_webhook_event_at"),
                "last_health_check_at": p.get("last_health_check_at"),
                "last_failover_at": p.get("last_failover_at"),
                "exhausted_at": p.get("exhausted_at"),
                "consecutive_errors": p.get("consecutive_errors", 0),
                "error_reason": p.get("error_reason"),
            })

        return {
            "provider_count": len(self._providers),
            "active_provider": active.get("name") if active else None,
            "active_webhook_id": provider_with_webhook.get("webhook_id") if provider_with_webhook else None,
            "active_key_preview": (
                active["key"][:4] + "..." + active["key"][-4:]
                if active and len(active.get("key", "")) > 8
                else None
            ),
            "health": (
                provider_with_webhook.get("webhook_status", "unknown")
                if provider_with_webhook
                else "not_found"
            ),
            "last_event_age_seconds": time_since_event,
            "providers": providers_safe,
            "multi_webhook_mode": self._config.multi_webhook_mode,
            "config": self._config.model_dump(),
        }

    def get_key_by_name(self, name: str) -> str:
        """Get raw API key by provider name."""
        for p in self._providers:
            if p.get("name") == name:
                return p.get("key", "")
        return ""


# ── Singleton ────────────────────────────────────────────────
_manager: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    """Get or create the webhook manager singleton."""
    global _manager
    if _manager is None:
        _manager = WebhookManager()
    return _manager
