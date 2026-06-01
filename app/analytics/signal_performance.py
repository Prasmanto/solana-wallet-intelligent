"""Signal performance — measures individual signal effectiveness."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SignalPerformance:
    """Measure individual signal effectiveness."""

    def __init__(self) -> None:
        self._signal_history: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        signal_name: str,
        value: float,
        success: bool,
        actual_return: float,
    ) -> None:
        """Record a signal observation."""
        if signal_name not in self._signal_history:
            self._signal_history[signal_name] = []

        self._signal_history[signal_name].append({
            "value": value,
            "success": success,
            "actual_return": actual_return,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def compute_performance(self, signal_name: str) -> dict[str, Any]:
        """Compute performance metrics for a signal."""
        history = self._signal_history.get(signal_name, [])
        if not history:
            return {"signal": signal_name, "total": 0}

        total = len(history)
        successful = sum(1 for h in history if h["success"])
        total_return = sum(h["actual_return"] for h in history if h["success"])

        return {
            "signal": signal_name,
            "total_observations": total,
            "successful_predictions": successful,
            "success_rate": successful / max(total, 1),
            "average_return": float(total_return / max(successful, 1)),
            "total_return": float(total_return),
        }

    def get_all_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance for all signals."""
        return {
            name: self.compute_performance(name)
            for name in self._signal_history
        }

    def get_top_signals(self, n: int = 5) -> list[dict[str, Any]]:
        """Get top N signals by success rate."""
        all_perf = self.get_all_performance()
        sorted_signals = sorted(
            all_perf.values(),
            key=lambda x: x.get("success_rate", 0),
            reverse=True,
        )
        return sorted_signals[:n]
