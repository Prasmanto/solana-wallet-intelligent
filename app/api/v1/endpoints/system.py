"""System health endpoint — VPS metrics."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/health",
    summary="VPS system health metrics",
)
async def system_health(request: Request) -> dict[str, Any]:
    """Return VPS system health metrics.

    Safe aggregate metrics only — no secrets, no private paths.
    """
    from app.api.v1.endpoints.dashboard import _get_vps_health
    return await _get_vps_health(request)
