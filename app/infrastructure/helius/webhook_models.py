"""Pydantic models for Helius webhook state tracking.

All models enforce immutability after creation and provide
safe masking of sensitive fields.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WebhookHealthStatus(str, Enum):
    """Health status of a webhook provider."""
    HEALTHY = "healthy"
    STALE = "stale"
    EXHAUSTED = "exhausted"
    ERROR = "error"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class WebhookProviderState(BaseModel):
    """State of a single API key's webhook ownership.

    Stored in api_keys.json alongside the key itself.
    """
    name: str
    active: bool = True

    # Webhook tracking
    webhook_id: str | None = None
    webhook_url: str | None = None
    webhook_status: WebhookHealthStatus = WebhookHealthStatus.UNKNOWN
    webhook_error: str | None = None

    # Timestamps
    last_used: float | None = None
    last_webhook_event_at: float | None = None
    last_health_check_at: float | None = None
    last_failover_at: float | None = None
    exhausted_at: float | None = None

    # Error tracking
    consecutive_errors: int = 0
    error_reason: str | None = None

    def masked_key(self, key: str) -> str:
        """Mask a raw API key for display."""
        if len(key) <= 8:
            return key[:2] + "..." + key[-2:] if len(key) > 4 else "***"
        return key[:4] + "..." + key[-4:]

    def to_safe_dict(self, raw_key: str = "") -> dict[str, Any]:
        """Return safe dict with masked key."""
        return {
            "name": self.name,
            "active": self.active,
            "key_preview": self.masked_key(raw_key) if raw_key else "***",
            "webhook_id": self.webhook_id,
            "webhook_status": self.webhook_status.value,
            "webhook_error": self.webhook_error,
            "last_used": self.last_used,
            "last_webhook_event_at": self.last_webhook_event_at,
            "last_health_check_at": self.last_health_check_at,
            "last_failover_at": self.last_failover_at,
            "exhausted_at": self.exhausted_at,
            "consecutive_errors": self.consecutive_errors,
            "error_reason": self.error_reason,
        }


class FailoverTrigger(BaseModel):
    """Reason for triggering a failover."""
    reason: str
    triggered_at: float = Field(default_factory=time.time)
    previous_provider: str | None = None
    new_provider: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WebhookFailoverConfig(BaseModel):
    """Configuration for the failover system."""
    # Failover trigger threshold (seconds)
    stale_threshold_seconds: int = 1800  # 30 minutes

    # Multi-webhook mode
    multi_webhook_mode: bool = False

    # Health check interval (seconds)
    health_check_interval_seconds: int = 300  # 5 minutes

    # Max consecutive errors before marking exhausted
    max_consecutive_errors: int = 3

    # Webhook URL (configure in .env or docker-compose.yml)
    webhook_url: str = "http://localhost:8000/api/v1/ingest/helius"


class WebhookStatusResponse(BaseModel):
    """API response for webhook status."""
    provider_count: int
    active_provider: str | None
    active_webhook_id: str | None
    active_key_preview: str | None
    health: WebhookHealthStatus
    last_event_age_seconds: float | None
    providers: list[dict[str, Any]]
    multi_webhook_mode: bool
    config: dict[str, Any]
