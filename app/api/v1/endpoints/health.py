"""Health check and metrics endpoints.

Provides:
- GET / — Health check (liveness)
- GET /deep — Deep health check (readiness)
- GET /metrics — Prometheus metrics
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.config.metrics import get_metrics
from app.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter()

_start_time = time.time()


@router.get(
    "/",
    summary="Health check",
)
async def health_check() -> dict[str, str]:
    """Lightweight health check. Returns 200 if process is alive."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": "0.1.0",
    }


@router.get(
    "/deep",
    summary="Deep health check",
)
async def health_deep(request: Request) -> dict[str, Any]:
    """Deep health check. Verifies DB and Redis connectivity."""
    checks = {}
    overall_healthy = True

    # Database check
    db_manager = getattr(request.app.state, "db_manager", None)
    if db_manager:
        try:
            db_health = await db_manager.health_check()
            checks["postgres"] = db_health
            if db_health.get("status") != "healthy":
                overall_healthy = False
        except Exception as e:
            checks["postgres"] = {"status": "unhealthy", "error": str(e)}
            overall_healthy = False
    else:
        checks["postgres"] = {"status": "not_initialized"}
        overall_healthy = False

    # Redis check
    redis_manager = getattr(request.app.state, "redis_manager", None)
    if redis_manager:
        try:
            redis_health = await redis_manager.health_check()
            checks["redis"] = redis_health
            if any(
                v.get("status") != "healthy"
                for v in redis_health.values()
                if isinstance(v, dict)
            ):
                overall_healthy = False
        except Exception as e:
            checks["redis"] = {"status": "unhealthy", "error": str(e)}
            overall_healthy = False
    else:
        checks["redis"] = {"status": "not_initialized"}
        overall_healthy = False

    uptime = time.time() - _start_time

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "service": settings.APP_NAME,
        "version": "0.1.0",
        "uptime_seconds": round(uptime, 2),
        "checks": checks,
    }


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics",
)
async def metrics_endpoint() -> str:
    """Expose Prometheus metrics for scraping."""
    return get_metrics().decode("utf-8")
