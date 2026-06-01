"""Weight optimizer — optimizes signal weights using outcome data."""

from __future__ import annotations

from typing import Any

import structlog

from app.self_learning.weight_learner import WeightLearner
from app.self_learning.signal_reliability import SignalReliabilityTracker

logger = structlog.get_logger(__name__)


class WeightOptimizer:
    """Optimizes signal weights based on outcome data."""

    def __init__(self) -> None:
        self._learner = WeightLearner()
        self._reliability = SignalReliabilityTracker()

    def optimize(
        self,
        outcomes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Optimize weights based on trade outcomes."""
        # Record outcomes for reliability tracking
        for outcome in outcomes:
            signals = outcome.get("signal_attribution", {})
            success = outcome.get("win_loss") == "WIN"
            actual_return = outcome.get("roi", 0.0)

            for signal_name, value in signals.items():
                if value > 0.1:
                    self._reliability.record(signal_name, success, actual_return)

        # Compute signal performance
        signal_performance = {}
        for signal_name, reliability in self._reliability.compute_all_reliability().items():
            signal_performance[signal_name] = {
                "success_rate": reliability.success_rate,
                "avg_return": reliability.return_quality * 20,  # Denormalize
            }

        # Adjust weights
        adjustments = self._learner.adjust_weights(signal_performance)

        return {
            "adjustments": len(adjustments),
            "weights": self._learner.get_weights(),
            "adjustment_details": [
                {
                    "signal": a.signal_name,
                    "old": a.old_weight,
                    "new": a.new_weight,
                    "change": a.adjustment_pct,
                }
                for a in adjustments
            ],
        }

    def get_reliability_scores(self) -> dict[str, float]:
        """Get current reliability scores."""
        return {
            name: rel.reliability_score
            for name, rel in self._reliability.compute_all_reliability().items()
        }

    def get_weights(self) -> dict[str, float]:
        """Get current weights."""
        return self._learner.get_weights()
