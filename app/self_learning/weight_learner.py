"""Weight learner — adjusts signal weights based on outcomes."""

from __future__ import annotations

import statistics
from typing import Any

import structlog

from app.self_learning.learning_models import WeightAdjustment

logger = structlog.get_logger(__name__)

# Safety limits
MAX_WEIGHT = 0.40
MIN_WEIGHT = 0.05
MAX_DAILY_ADJUSTMENT = 0.05
EMA_ALPHA = 0.1  # Slow adaptation


class WeightLearner:
    """Adjusts signal weights based on outcome data."""

    def __init__(self) -> None:
        self._current_weights: dict[str, float] = {
            "smart_money": 0.25,
            "cluster_convergence": 0.20,
            "liquidity": 0.15,
            "momentum": 0.10,
            "lead_lag": 0.10,
            "anomaly": 0.05,
            "pump_prediction": 0.05,
        }
        self._weight_history: list[dict[str, Any]] = []
        self._last_adjustment: dict[str, float] = {}

    def adjust_weights(
        self,
        signal_performance: dict[str, dict[str, Any]],
    ) -> list[WeightAdjustment]:
        """Adjust weights based on signal performance."""
        adjustments = []

        for signal_name, old_weight in self._current_weights.items():
            perf = signal_performance.get(signal_name, {})
            success_rate = perf.get("success_rate", 0.5)
            avg_return = perf.get("avg_return", 0.0)

            # Compute adjustment
            adjustment = self._compute_adjustment(
                old_weight, success_rate, avg_return
            )

            # Apply safety limits
            new_weight = self._apply_safety(old_weight, adjustment)

            # Record adjustment
            if abs(new_weight - old_weight) > 0.001:
                adj_pct = ((new_weight - old_weight) / old_weight) * 100

                adjustments.append(WeightAdjustment(
                    signal_name=signal_name,
                    old_weight=old_weight,
                    new_weight=new_weight,
                    adjustment_pct=float(adj_pct),
                    reason=f"success_rate={success_rate:.2f}, avg_return={avg_return:.2f}",
                    metrics_used={
                        "success_rate": success_rate,
                        "avg_return": avg_return,
                    },
                ))

                self._current_weights[signal_name] = new_weight

        # Normalize weights
        self._normalize_weights()

        return adjustments

    def _compute_adjustment(
        self,
        old_weight: float,
        success_rate: float,
        avg_return: float,
    ) -> float:
        """Compute weight adjustment based on performance."""
        # Target weight based on performance
        # Higher success rate and return = higher weight
        performance_score = success_rate * (1 + min(avg_return / 100, 0.5))
        target_weight = performance_score * MAX_WEIGHT

        # EMA update (slow adaptation)
        new_weight = old_weight + EMA_ALPHA * (target_weight - old_weight)

        return new_weight

    def _apply_safety(self, old_weight: float, new_weight: float) -> float:
        """Apply safety limits to weight adjustment."""
        # Limit daily adjustment
        change = abs(new_weight - old_weight)
        if change > MAX_DAILY_ADJUSTMENT:
            if new_weight > old_weight:
                new_weight = old_weight + MAX_DAILY_ADJUSTMENT
            else:
                new_weight = old_weight - MAX_DAILY_ADJUSTMENT

        # Enforce bounds
        new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))

        return new_weight

    def _normalize_weights(self) -> None:
        """Normalize weights to sum to 1.0."""
        total = sum(self._current_weights.values())
        if total > 0:
            for signal in self._current_weights:
                self._current_weights[signal] /= total

    def get_weights(self) -> dict[str, float]:
        """Get current weights."""
        return dict(self._current_weights)


MAX_WEIGHT = 0.40
MIN_WEIGHT = 0.05
MAX_DAILY_ADJUSTMENT = 0.05
EMA_ALPHA = 0.1
