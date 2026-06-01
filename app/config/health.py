"""Health monitoring — service health checks and status.

Provides:
- Service health status
- Dependency health checks
- Readiness/liveness probes
- Shadow-mode status
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from redis.asyncio import Redis

from app.config import settings

logger = structlog.get_logger(__name__)

# ── Health Status ───────────────────────────────────────────

_start_time = time.time()

HEALTH_STATUS = {
    "service": "solana-wallet-intel",
    "version": "0.1.0",
    "status": "healthy",
    "started_at": datetime.now(timezone.utc).isoformat(),
}


class HealthChecker:
    """Service health checker."""

    def __init__(self) -> None:
        self._checks: dict[str, Any] = {}

    async def check_all(
        self,
        db_manager: Any = None,
        redis_manager: Any = None,
    ) -> dict[str, Any]:
        """Run all health checks."""
        checks = {
            "status": "healthy",
            "service": HEALTH_STATUS["service"],
            "version": HEALTH_STATUS["version"],
            "env": settings.APP_ENV,
            "uptime_seconds": round(time.time() - _start_time, 2),
            "started_at": HEALTH_STATUS["started_at"],
            "checks": {},
        }

        # Database check
        if db_manager:
            try:
                db_health = await db_manager.health_check()
                checks["checks"]["postgres"] = db_health
                if db_health.get("status") != "healthy":
                    checks["status"] = "degraded"
            except Exception as e:
                checks["checks"]["postgres"] = {"status": "unhealthy", "error": str(e)}
                checks["status"] = "degraded"

        # Redis check
        if redis_manager:
            try:
                redis_health = await redis_manager.health_check()
                checks["checks"]["redis"] = redis_health
                if any(
                    v.get("status") != "healthy"
                    for v in redis_health.values()
                    if isinstance(v, dict)
                ):
                    checks["status"] = "degraded"
            except Exception as e:
                checks["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
                checks["status"] = "degraded"

        return checks

    def check_workers(
        self,
        worker_statuses: dict[str, str],
    ) -> dict[str, Any]:
        """Check worker health."""
        unhealthy = [
            name
            for name, status in worker_statuses.items()
            if status != "healthy"
        ]

        return {
            "status": "healthy" if not unhealthy else "degraded",
            "workers": worker_statuses,
            "unhealthy_workers": unhealthy,
        }

    def check_streams(
        self,
        stream_depths: dict[str, int],
        thresholds: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Check stream health based on depth thresholds."""
        if thresholds is None:
            thresholds = {
                "solana_intel.raw.pending": 10000,
                "solana_intel.raw.stored": 10000,
                "solana_intel.trade.normalized": 5000,
                "solana_intel.dead_letter": 100,
            }

        warnings = []
        for stream, depth in stream_depths.items():
            threshold = thresholds.get(stream, 10000)
            if depth > threshold:
                warnings.append(f"{stream}: {depth} > {threshold}")

        return {
            "status": "healthy" if not warnings else "warning",
            "stream_depths": stream_depths,
            "warnings": warnings,
        }


# ── Shadow Mode ─────────────────────────────────────────────

class ShadowMode:
    """Shadow mode configuration for production deployment.

    Shadow mode allows running the new system alongside the existing
    system without affecting production traffic.
    """

    def __init__(self) -> None:
        self._enabled = settings.APP_ENV == "development"
        self._metrics_only = False

    @property
    def enabled(self) -> bool:
        """Check if shadow mode is enabled."""
        return self._enabled

    @property
    def metrics_only(self) -> bool:
        """Check if running in metrics-only mode."""
        return self._metrics_only

    def enable(self, metrics_only: bool = False) -> None:
        """Enable shadow mode."""
        self._enabled = True
        self._metrics_only = metrics_only
        logger.info(
            "shadow_mode.enabled",
            metrics_only=metrics_only,
        )

    def disable(self) -> None:
        """Disable shadow mode."""
        self._enabled = False
        self._metrics_only = False
        logger.info("shadow_mode.disabled")

    def should_process(self) -> bool:
        """Check if events should be processed (not just observed)."""
        if not self._enabled:
            return True
        return not self._metrics_only

    def get_status(self) -> dict[str, Any]:
        """Get shadow mode status."""
        return {
            "enabled": self._enabled,
            "metrics_only": self._metrics_only,
            "mode": "shadow" if self._enabled else "active",
        }


# ── Global Instances ────────────────────────────────────────

health_checker = HealthChecker()
shadow_mode = ShadowMode()
