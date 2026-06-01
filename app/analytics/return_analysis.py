"""Return analysis — analyzes return distributions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ReturnAnalysis:
    """Analyze return distributions."""

    def __init__(self) -> None:
        self._returns: list[dict[str, Any]] = []

    def record(
        self,
        prediction_type: str,
        actual_return: float,
        confidence: float,
    ) -> None:
        """Record a return observation."""
        self._returns.append({
            "prediction_type": prediction_type,
            "actual_return": actual_return,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def compute_statistics(self) -> dict[str, Any]:
        """Compute return statistics."""
        if not self._returns:
            return {"total": 0}

        returns = [r["actual_return"] for r in self._returns]
        returns_float = [float(r) for r in returns]

        return {
            "total": len(returns),
            "average_return": sum(returns_float) / len(returns_float),
            "median_return": sorted(returns_float)[len(returns_float) // 2],
            "min_return": min(returns_float),
            "max_return": max(returns_float),
            "std_dev": self._compute_std_dev(returns_float),
            "positive_count": sum(1 for r in returns if r > 0),
            "negative_count": sum(1 for r in returns if r < 0),
        }

    def _compute_std_dev(self, values: list[float]) -> float:
        """Compute standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return float(variance ** 0.5)

    def get_top_returns(self, n: int = 5) -> list[dict[str, Any]]:
        """Get top N returns."""
        sorted_returns = sorted(
            self._returns,
            key=lambda x: x["actual_return"],
            reverse=True,
        )
        return sorted_returns[:n]
