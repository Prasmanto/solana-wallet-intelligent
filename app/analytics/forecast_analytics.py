"""Forecast analytics — analyzes forecast performance by regime and token."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ForecastAnalytics:
    """Analyze forecast performance by regime and token."""

    def __init__(self) -> None:
        self._regime_stats: dict[str, dict[str, Any]] = {}
        self._token_stats: dict[str, dict[str, Any]] = {}
        self._horizon_stats: dict[str, dict[str, Any]] = {}

    def record(
        self,
        regime: str,
        token: str,
        horizon: str,
        success: bool,
        actual_return: float,
        confidence: float,
    ) -> None:
        """Record a prediction outcome."""
        # Regime stats
        if regime not in self._regime_stats:
            self._regime_stats[regime] = {"total": 0, "successful": 0, "return": 0.0}
        self._regime_stats[regime]["total"] += 1
        if success:
            self._regime_stats[regime]["successful"] += 1
            self._regime_stats[regime]["return"] += actual_return

        # Token stats
        if token not in self._token_stats:
            self._token_stats[token] = {"total": 0, "successful": 0, "return": 0.0}
        self._token_stats[token]["total"] += 1
        if success:
            self._token_stats[token]["successful"] += 1
            self._token_stats[token]["return"] += actual_return

        # Horizon stats
        if horizon not in self._horizon_stats:
            self._horizon_stats[horizon] = {"total": 0, "successful": 0, "return": 0.0}
        self._horizon_stats[horizon]["total"] += 1
        if success:
            self._horizon_stats[horizon]["successful"] += 1
            self._horizon_stats[horizon]["return"] += actual_return

    def compute_regime_performance(self) -> dict[str, dict[str, Any]]:
        """Compute performance by regime."""
        results = {}
        for regime, stats in self._regime_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["return"]

            results[regime] = {
                "accuracy": successful / max(total, 1),
                "total_predictions": total,
                "average_return": float(total_return / max(successful, 1)),
            }
        return results

    def compute_token_performance(self) -> dict[str, dict[str, Any]]:
        """Compute performance by token."""
        results = {}
        for token, stats in self._token_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["return"]

            results[token] = {
                "accuracy": successful / max(total, 1),
                "total_predictions": total,
                "average_return": float(total_return / max(successful, 1)),
            }
        return results

    def compute_horizon_performance(self) -> dict[str, dict[str, Any]]:
        """Compute performance by horizon."""
        results = {}
        for horizon, stats in self._horizon_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["return"]

            results[horizon] = {
                "accuracy": successful / max(total, 1),
                "total_predictions": total,
                "average_return": float(total_return / max(successful, 1)),
            }
        return results
