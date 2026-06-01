"""Signal reliability — computes reliability scores for signals."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

import structlog

from app.self_learning.learning_models import SignalReliability

logger = structlog.get_logger(__name__)


class SignalReliabilityTracker:
    """Tracks and computes signal reliability scores."""

    def __init__(self) -> None:
        self._signal_history: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        signal_name: str,
        success: bool,
        actual_return: float,
    ) -> None:
        """Record a signal observation."""
        if signal_name not in self._signal_history:
            self._signal_history[signal_name] = []

        self._signal_history[signal_name].append({
            "success": success,
            "actual_return": actual_return,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def compute_reliability(self, signal_name: str) -> SignalReliability:
        """Compute reliability score for a signal."""
        history = self._signal_history.get(signal_name, [])

        if not history:
            return SignalReliability(
                signal_name=signal_name,
                success_rate=0.0,
                return_quality=0.0,
                sample_size=0,
                stability=0.0,
                reliability_score=0.0,
            )

        # Success rate
        successes = sum(1 for h in history if h["success"])
        success_rate = successes / len(history)

        # Return quality
        returns = [h["actual_return"] for h in history if h["success"]]
        avg_return = sum(returns) / len(returns) if returns else 0.0
        return_quality = min(1.0, max(0.0, avg_return / 20.0))  # Normalize

        # Sample size score
        sample_score = min(1.0, len(history) / 50)  # 50 samples = full score

        # Stability (low variance in returns)
        if len(returns) >= 2:
            stdev = statistics.stdev(returns)
            stability = max(0.0, 1.0 - stdev / 20.0)
        else:
            stability = 0.5

        # Combined reliability score
        reliability = (
            0.4 * success_rate +
            0.3 * return_quality +
            0.2 * sample_score +
            0.1 * stability
        )

        return SignalReliability(
            signal_name=signal_name,
            success_rate=success_rate,
            return_quality=return_quality,
            sample_size=len(history),
            stability=stability,
            reliability_score=reliability,
        )

    def compute_all_reliability(self) -> dict[str, SignalReliability]:
        """Compute reliability for all signals."""
        return {
            name: self.compute_reliability(name)
            for name in self._signal_history
        }
