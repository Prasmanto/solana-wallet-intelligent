"""Engine comparison — compares prediction engine performance."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EngineComparison:
    """Compare prediction engine performance."""

    def __init__(self) -> None:
        self._engine_stats: dict[str, dict[str, Any]] = {}

    def record(
        self,
        engine_name: str,
        success: bool,
        actual_return: float,
        confidence: float,
    ) -> None:
        """Record a prediction outcome for an engine."""
        if engine_name not in self._engine_stats:
            self._engine_stats[engine_name] = {
                "total": 0,
                "successful": 0,
                "total_return": 0.0,
                "confidences": [],
            }

        stats = self._engine_stats[engine_name]
        stats["total"] += 1
        if success:
            stats["successful"] += 1
            stats["total_return"] += actual_return
        stats["confidences"].append(confidence)

    def compute_comparison(self) -> dict[str, dict[str, Any]]:
        """Compute comparison metrics for all engines."""
        comparison = {}

        for engine_name, stats in self._engine_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["total_return"]
            confidences = stats["confidences"]

            success_rate = successful / max(total, 1)
            avg_return = total_return / max(successful, 1)

            # Sharpe-like score (simplified)
            if confidences:
                avg_confidence = sum(confidences) / len(confidences)
                sharpe = float(avg_return * success_rate * avg_confidence)
            else:
                sharpe = 0.0

            comparison[engine_name] = {
                "accuracy": float(success_rate),
                "precision": float(success_rate),
                "recall": float(success_rate),
                "win_rate": float(success_rate),
                "average_return": float(avg_return),
                "expected_value": float(avg_return * success_rate),
                "sharpe_score": float(sharpe),
                "total_predictions": total,
                "successful_predictions": successful,
            }

        return comparison

    def get_top_engines(self, n: int = 3) -> list[dict[str, Any]]:
        """Get top N engines by accuracy."""
        comparison = self.compute_comparison()
        sorted_engines = sorted(
            comparison.items(),
            key=lambda x: x[1]["accuracy"],
            reverse=True,
        )
        return [
            {"engine": name, **stats}
            for name, stats in sorted_engines[:n]
        ]

    def get_engine_details(self, engine_name: str) -> dict[str, Any]:
        """Get detailed metrics for a specific engine."""
        comparison = self.compute_comparison()
        return comparison.get(engine_name, {})
