"""Alpha attribution — identifies which signals generate alpha."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

SIGNAL_NAMES = [
    "smart_money",
    "cluster_convergence",
    "liquidity",
    "momentum",
    "lead_lag",
    "anomaly",
]


class AlphaAttribution:
    """Compute signal contribution to successful predictions."""

    def __init__(self) -> None:
        self._signal_stats: dict[str, dict[str, Any]] = {
            name: {
                "total": 0,
                "successful": 0,
                "total_return": 0.0,
            }
            for name in SIGNAL_NAMES
        }

    def record_prediction(
        self,
        signals: dict[str, float],
        success: bool,
        actual_return: float,
    ) -> None:
        """Record a prediction outcome for attribution."""
        for signal_name, value in signals.items():
            if signal_name in self._signal_stats and value > 0.1:
                self._signal_stats[signal_name]["total"] += 1
                if success:
                    self._signal_stats[signal_name]["successful"] += 1
                    self._signal_stats[signal_name]["total_return"] += actual_return

    def compute_attribution(self) -> dict[str, Any]:
        """Compute alpha attribution for all signals."""
        attribution = {}

        for signal_name, stats in self._signal_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["total_return"]

            success_rate = successful / max(total, 1)
            avg_return = total_return / max(successful, 1)

            attribution[signal_name] = {
                "success_rate": float(success_rate),
                "average_return": float(avg_return),
                "total_predictions": total,
                "successful_predictions": successful,
            }

        return attribution

    def get_top_signals(self, n: int = 3) -> list[dict[str, Any]]:
        """Get top N signals by success rate."""
        attribution = self.compute_attribution()
        sorted_signals = sorted(
            attribution.items(),
            key=lambda x: x[1]["success_rate"],
            reverse=True,
        )
        return [
            {"signal": name, **stats}
            for name, stats in sorted_signals[:n]
        ]

    def get_correlation_analysis(
        self,
        predictions: list[dict[str, Any]],
    ) -> dict[str, tuple[float, float]]:
        """Compute signal pair effectiveness."""
        pair_stats: dict[str, dict[str, Any]] = {}

        for pred in predictions:
            signals = pred.get("signals", {})
            success = pred.get("success", False)
            actual_return = pred.get("actual_return", 0.0)

            active_signals = [s for s, v in signals.items() if v > 0.1]

            for i, s1 in enumerate(active_signals):
                for s2 in active_signals[i+1:]:
                    pair_key = tuple(sorted([s1, s2]))
                    if pair_key not in pair_stats:
                        pair_stats[pair_key] = {"total": 0, "successful": 0, "return": 0.0}

                    pair_stats[pair_key]["total"] += 1
                    if success:
                        pair_stats[pair_key]["successful"] += 1
                        pair_stats[pair_key]["return"] += actual_return

        # Compute pair metrics
        pair_metrics = {}
        for pair, stats in pair_stats.items():
            total = stats["total"]
            successful = stats["successful"]
            total_return = stats["return"]

            pair_metrics[f"{pair[0]}+{pair[1]}"] = {
                "pair_accuracy": successful / max(total, 1),
                "pair_average_return": float(total_return / max(successful, 1)),
                "total_pairs": total,
            }

        return pair_metrics
