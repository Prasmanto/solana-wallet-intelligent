"""Learning manager — orchestrates adaptive learning cycles."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.self_learning.weight_optimizer import WeightOptimizer
from app.self_learning.learning_models import LearningCycle

logger = structlog.get_logger(__name__)


class LearningManager:
    """Orchestrates adaptive learning cycles."""

    def __init__(self) -> None:
        self._optimizer = WeightOptimizer()
        self._cycles: list[LearningCycle] = []
        self._cycle_count = 0

    async def run_learning_cycle(
        self,
        outcomes: list[dict[str, Any]],
    ) -> LearningCycle:
        """Run a learning cycle based on trade outcomes."""
        self._cycle_count += 1

        # Run optimization
        result = self._optimizer.optimize(outcomes)

        # Create cycle record
        cycle = LearningCycle(
            cycle_id=str(uuid.uuid4()),
            signals_adjusted=result.get("adjustments", 0),
            total_signals=len(result.get("weights", {})),
            adaptation_rate=result.get("adjustments", 0) / max(len(result.get("weights", {})), 1),
            weight_stability=self._compute_weight_stability(result.get("weights", {})),
        )

        self._cycles.append(cycle)

        logger.info(
            "learning.cycle_completed",
            cycle_id=cycle.cycle_id[:16],
            signals_adjusted=cycle.signals_adjusted,
            adaptation_rate=cycle.adaptation_rate,
            weight_stability=cycle.weight_stability,
        )

        return cycle

    def _compute_weight_stability(self, weights: dict[str, float]) -> float:
        """Compute weight stability score."""
        if not weights:
            return 0.0

        values = list(weights.values())
        if len(values) < 2:
            return 1.0

        # Lower variance = more stable
        mean = sum(values) / len(values)
        if mean == 0:
            return 0.0

        stdev = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        cv = stdev / mean  # Coefficient of variation

        # CV < 0.1 = very stable, CV > 0.5 = unstable
        return max(0.0, min(1.0, 1.0 - cv))

    def get_current_weights(self) -> dict[str, float]:
        """Get current signal weights."""
        return self._optimizer.get_weights()

    def get_reliability_scores(self) -> dict[str, float]:
        """Get current reliability scores."""
        return self._optimizer.get_reliability_scores()

    def get_learning_history(self, limit: int = 10) -> list[LearningCycle]:
        """Get recent learning cycles."""
        return self._cycles[-limit:]

    def get_health(self) -> dict[str, Any]:
        """Get learning system health."""
        weights = self._optimizer.get_weights()
        reliability = self._optimizer.get_reliability_scores()

        return {
            "cycle_count": self._cycle_count,
            "total_signals": len(weights),
            "avg_reliability": sum(reliability.values()) / len(reliability) if reliability else 0.0,
            "weight_sum": sum(weights.values()),
            "last_cycle": self._cycles[-1].timestamp if self._cycles else None,
        }
