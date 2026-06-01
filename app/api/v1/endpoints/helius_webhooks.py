"""Helius webhook management endpoints — admin only.

Security:
- All endpoints require admin auth (Bearer token via ADMIN_API_TOKEN)
- Rate limited to 10 req/min per IP
- API keys masked in responses
- Audit logging for all state changes
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.infrastructure.helius.helius_client import HeliusApiError
from app.infrastructure.helius.webhook_failover import get_webhook_failover
from app.infrastructure.helius.webhook_manager import get_webhook_manager

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

# ── Rate Limiter ────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 10
RATE_WINDOW = 60


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request) -> None:
    ip = _get_client_ip(request)
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Max 10 requests per minute.",
        )
    _rate_store[ip].append(now)


def _verify_admin_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    token = os.environ.get("ADMIN_API_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin authentication not configured",
        )
    if credentials is None or credentials.credentials != token:
        ip = _get_client_ip(request)
        logger.warning("helius_webhooks.auth_failed", ip=ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def _audit_log(action: str, details: dict[str, Any] | None = None) -> None:
    logger.info(
        "helius_webhooks.audit",
        action=action,
        actor="admin",
        timestamp=datetime.now(timezone.utc).isoformat(),
        **(details or {}),
    )


# ── Response Models ─────────────────────────────────────────
class WebhookStatusResponse(BaseModel):
    provider_count: int
    active_provider: str | None
    active_webhook_id: str | None
    active_key_preview: str | None
    health: str
    last_event_age_seconds: float | None
    providers: list[dict[str, Any]]
    multi_webhook_mode: bool
    config: dict[str, Any]


class FailoverResponse(BaseModel):
    status: str
    message: str
    trigger: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []


class CreateWebhookResponse(BaseModel):
    status: str
    provider: str
    webhook_id: str | None = None
    message: str


class ResetHealthResponse(BaseModel):
    status: str
    provider: str
    message: str


# ── Endpoints ───────────────────────────────────────────────
@router.get(
    "/webhooks/status",
    response_model=WebhookStatusResponse,
    summary="Webhook provider status (admin only)",
)
async def get_webhook_status(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> WebhookStatusResponse:
    """Get status of all webhook providers, active webhook, and health."""
    _check_rate_limit(request)
    manager = get_webhook_manager()
    manager.reload()
    status_data = manager.get_status()

    _audit_log("status-check")

    return WebhookStatusResponse(**status_data)


@router.post(
    "/webhooks/failover",
    response_model=FailoverResponse,
    summary="Trigger failover to next provider (admin only)",
)
async def trigger_failover(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> FailoverResponse:
    """Check health and failover to next available provider if needed."""
    _check_rate_limit(request)
    manager = get_webhook_manager()
    manager.reload()
    failover = get_webhook_failover()

    trigger = await failover.failover(force=True)

    if trigger:
        _audit_log(
            "failover",
            details={
                "reason": trigger.reason,
                "from": trigger.previous_provider,
                "to": trigger.new_provider,
            },
        )
        return FailoverResponse(
            status="ok",
            message=f"Failover performed: {trigger.previous_provider} → {trigger.new_provider}",
            trigger={
                "reason": trigger.reason,
                "previous_provider": trigger.previous_provider,
                "new_provider": trigger.new_provider,
                "triggered_at": trigger.triggered_at,
                "details": trigger.details,
            },
            history=failover.get_failover_history(),
        )

    _audit_log("failover-check", details={"result": "no_failover_needed"})
    return FailoverResponse(
        status="ok",
        message="Current provider is healthy, no failover needed",
        history=failover.get_failover_history(),
    )


@router.post(
    "/webhooks/create-current",
    response_model=CreateWebhookResponse,
    summary="Create webhook for current provider (admin only)",
)
async def create_webhook_for_current(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> CreateWebhookResponse:
    """Create a webhook using the current active provider's API key."""
    _check_rate_limit(request)
    manager = get_webhook_manager()
    manager.reload()
    failover = get_webhook_failover()

    provider = manager.get_active_provider()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active provider found",
        )

    name = provider.get("name", "unknown")

    webhook_id = await failover.create_webhook_for_current()

    if webhook_id:
        _audit_log("create-webhook", details={"provider": name, "webhook_id": webhook_id})
        return CreateWebhookResponse(
            status="ok",
            provider=name,
            webhook_id=webhook_id,
            message=f"Webhook created for {name}",
        )

    _audit_log("create-webhook-failed", details={"provider": name})
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Failed to create webhook for {name}",
    )


@router.post(
    "/webhooks/mark-current-exhausted",
    response_model=FailoverResponse,
    summary="Mark current provider exhausted (admin only)",
)
async def mark_current_exhausted(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> FailoverResponse:
    """Manually mark current provider as exhausted and trigger failover."""
    _check_rate_limit(request)
    manager = get_webhook_manager()
    manager.reload()
    failover = get_webhook_failover()

    provider = manager.get_active_provider()
    if provider:
        name = provider.get("name", "unknown")
        manager.mark_provider_exhausted(name, reason="manual_mark_exhausted")
        _audit_log("mark-exhausted", details={"provider": name})

    trigger = await failover.failover(force=True)

    if trigger:
        return FailoverResponse(
            status="ok",
            message=f"Marked exhausted and failed over: {trigger.previous_provider} → {trigger.new_provider}",
            trigger={
                "reason": trigger.reason,
                "previous_provider": trigger.previous_provider,
                "new_provider": trigger.new_provider,
                "triggered_at": trigger.triggered_at,
            },
            history=failover.get_failover_history(),
        )

    return FailoverResponse(
        status="ok",
        message="Marked exhausted but no providers available for failover",
        history=failover.get_failover_history(),
    )


@router.post(
    "/webhooks/reset-health",
    response_model=ResetHealthResponse,
    summary="Reset provider health status (admin only)",
)
async def reset_provider_health(
    provider_name: str,
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> ResetHealthResponse:
    """Reset a provider's health status to active."""
    _check_rate_limit(request)
    manager = get_webhook_manager()
    manager.reload()
    failover = get_webhook_failover()

    success = await failover.reset_provider_health(provider_name)

    if success:
        _audit_log("reset-health", details={"provider": provider_name})
        return ResetHealthResponse(
            status="ok",
            provider=provider_name,
            message=f"Provider {provider_name} health reset to active",
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Provider {provider_name} not found",
    )
