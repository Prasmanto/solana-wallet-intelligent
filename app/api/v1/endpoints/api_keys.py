"""API Key management endpoints — production-hardened.

Security:
- All endpoints require admin auth (Bearer token via ADMIN_API_TOKEN)
- Rate limited to 10 req/min per IP
- API keys masked in responses (abcd...7890)
- Audit logging for all state changes
- No secrets in logs
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config.api_key_manager import get_api_key_manager

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

# ── Rate Limiter ────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 10  # requests per minute
RATE_WINDOW = 60  # seconds


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
        logger.warning("api_keys.rate_limited", ip=ip, count=len(_rate_store[ip]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Max 10 requests per minute.",
        )
    _rate_store[ip].append(now)


# ── Auth Dependency ─────────────────────────────────────────
def _verify_admin_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    token = os.environ.get("ADMIN_API_TOKEN", "")
    if not token:
        logger.error("api_keys.admin_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin authentication not configured",
        )

    if credentials is None or credentials.credentials != token:
        ip = _get_client_ip(request)
        logger.warning("api_keys.auth_failed", ip=ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


# ── Key Masking ─────────────────────────────────────────────
def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return key[:2] + "..." + key[-2:] if len(key) > 4 else "***"
    return key[:4] + "..." + key[-4:]


# ── Audit Logging ───────────────────────────────────────────
def _audit_log(
    action: str,
    previous_key_name: str = "",
    new_key_name: str = "",
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "api_keys.audit",
        action=action,
        previous_key=previous_key_name,
        new_key=new_key_name,
        actor="admin",
        success=success,
        timestamp=datetime.now(timezone.utc).isoformat(),
        **(details or {}),
    )


# ── Response Models ─────────────────────────────────────────
class MaskedKeyInfo(BaseModel):
    name: str
    key_preview: str
    active: bool
    exhausted_at: float | None = None


class KeyStatus(BaseModel):
    total_keys: int
    current_index: int
    current_key_name: str
    active_keys: int
    cooldown_remaining: float
    keys: list[MaskedKeyInfo]


class RotateRequest(BaseModel):
    cooldown_seconds: int = 3600


class RotateResponse(BaseModel):
    status: str
    message: str
    current_key: str


# ── Endpoints ───────────────────────────────────────────────
@router.get(
    "/status",
    response_model=KeyStatus,
    summary="API key rotation status (admin only)",
)
async def get_status(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> KeyStatus:
    _check_rate_limit(request)
    manager = get_api_key_manager()
    raw = manager.get_status()

    masked_keys = []
    for k in raw["keys"]:
        key_obj = next((x for x in manager._keys if x.get("name") == k["name"]), None)
        raw_key = key_obj["key"] if key_obj else ""
        masked_keys.append(MaskedKeyInfo(
            name=k["name"],
            key_preview=_mask_key(raw_key),
            active=k["active"],
            exhausted_at=k.get("exhausted_at"),
        ))

    return KeyStatus(
        total_keys=raw["total_keys"],
        current_index=raw["current_index"],
        current_key_name=raw["current_key_name"],
        active_keys=raw["active_keys"],
        cooldown_remaining=raw["cooldown_remaining"],
        keys=masked_keys,
    )


@router.post(
    "/test-rotate",
    response_model=RotateResponse,
    summary="Mark current key exhausted, rotate to next (admin only)",
)
async def test_rotate(
    req: RotateRequest,
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> RotateResponse:
    _check_rate_limit(request)
    manager = get_api_key_manager()

    prev_index = manager._current_index
    prev_name = manager._keys[prev_index].get("name", "unknown") if manager._keys else "none"

    manager.mark_exhausted(cooldown_seconds=req.cooldown_seconds)

    new_index = manager._current_index
    new_name = manager._keys[new_index].get("name", "unknown") if manager._keys else "none"

    _audit_log(
        action="test-rotate",
        previous_key_name=prev_name,
        new_key_name=new_name,
        details={"cooldown_seconds": req.cooldown_seconds},
    )

    return RotateResponse(
        status="ok",
        message=f"Rotated from {prev_name} to {new_name}",
        current_key=f"{new_name}: {_mask_key(manager.get_current_key())}",
    )


@router.post(
    "/reset",
    response_model=RotateResponse,
    summary="Reset all keys to active (admin only)",
)
async def reset_keys(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> RotateResponse:
    _check_rate_limit(request)
    manager = get_api_key_manager()
    count = len(manager._keys)

    for key in manager._keys:
        key["active"] = True
        key.pop("exhausted_at", None)
    manager._current_index = 0
    manager._cooldown_until = 0
    manager._save_config()

    _audit_log(
        action="reset",
        previous_key_name=f"index={manager._current_index}",
        new_key_name="key_01",
        details={"reset_count": count},
    )

    return RotateResponse(
        status="ok",
        message=f"Reset all {count} keys to active",
        current_key=f"key_01: {_mask_key(manager.get_current_key())}",
    )


@router.post(
    "/mark-working",
    response_model=RotateResponse,
    summary="Mark current key as working (admin only)",
)
async def mark_working_endpoint(
    request: Request,
    token: str = Depends(_verify_admin_token),
) -> RotateResponse:
    _check_rate_limit(request)
    manager = get_api_key_manager()

    prev_name = manager._keys[manager._current_index].get("name", "unknown") if manager._keys else "none"
    manager.mark_working()

    current = manager.get_current_key()
    name = manager._keys[manager._current_index].get("name", "unknown") if manager._keys else "none"

    _audit_log(
        action="mark-working",
        previous_key_name=prev_name,
        new_key_name=name,
    )

    return RotateResponse(
        status="ok",
        message=f"Key {name} marked as working",
        current_key=f"{name}: {_mask_key(current)}",
    )
