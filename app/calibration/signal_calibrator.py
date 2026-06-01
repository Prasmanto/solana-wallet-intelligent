"""Signal calibrator — adjusts signal weights based on performance."""

from __future__ import annotations

import math
from typing import Any

import structlog

from app.calibration.calibration_models import SignalCalibration

logger = structlog.get_logger(__name__)

# Calibration constraints
MAX_WEIGHT = 0.40
MIN_WEIGHT = 0.05
MAX_WEIGHT_CHANGE = 0.20


class SignalCalibrator:
    """Calibrates signal weights based on historical performance."""

    def __init__(self) -> None:
        self._current_weights: dict[str, float] = {
            "smart_money": 0.25,
            "cluster_convergence": 0.20,
            "liquidity": 0.15,
            "momentum": 0.10,
            "lead_lag": 0.10,
            "anomaly": 0.05,
        }

    def calibrate(
        self,
        signal_attribution: dict[str, dict[str, Any]],
    ) -> list[SignalCalibration]:
        """Calibrate signal weights based on attribution data."""
        calibrated = []

        for signal_name, old_weight in self._current_weights.items():
            stats = signal_attribution.get(signal_name, {})
            success_rate = stats.get("success_rate", 0.0)
            avg_return = stats.get("average_return", 0.0)

            # Compute new weight based on success rate
            new_weight = self._compute_weight(
                old_weight, success_rate, avg_return
            )

            calibrated.append(SignalCalibration(
                signal_name=signal_name,
                old_weight=old_weight,
                new_weight=new_weight,
                success_rate=success_rate,
                average_return=avg_return,
                confidence=success_rate,
            ))

        # Normalize weights to sum to 1.0
        calibrated = self._normalize_weights(calibrated)

        # Apply safety guards
        calibrated = self._apply_safety_guards(calibrated)

        # Update current weights
        for sig in calibrated:
            self._current_weights[sig.signal_name] = sig.new_weight

        return calibrated

    def _compute_weight(
        self,
        old_weight: float,
        success_rate: float,
        avg_return: float,
    ) -> float:
        """Compute new weight based on performance."""
        # Higher success rate and return = higher weight
        performance_score = success_rate * (1 + min(avg_return / 100, 1.0))

        # Map to weight range (0.05 - 0.40)
        new_weight = performance_score * 0.40

        # Apply EMA smoothing (prevent extreme changes)
        smoothed = 0.7 * old_weight + 0.3 * new_weight

        return float(max(MIN_WEIGHT, min(MAX_WEIGHT, smoothed)))

    def _normalize_weights(
        self,
        calibrated: list[SignalCalibration],
    ) -> list[SignalCalibration]:
        """Normalize weights to sum to 1.0."""
        total = sum(c.new_weight for c in calibrated)
        if total == 0:
            return calibrated

        for c in calibrated:
            c.new_weight = c.new_weight / total

        return calibrated

    def _apply_safety_guards(
        self,
        calibrated: list[SignalCalibration],
    ) -> list[SignalCalibration]:
        """Apply safety guards to prevent extreme changes."""
        for c in calibrated:
            # Limit weight change
            weight_change = abs(c.new_weight - c.old_weight)
            if weight_change > MAX_WEIGHT_CHANGE:
                if c.new_weight > c.old_weight:
                    c.new_weight = c.old_weight + MAX_WEIGHT_CHANGE
                else:
                    c.new_weight = c.old_weight - MAX_WEIGHT_CHANGE

            # Enforce bounds
            c.new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, c.new_weight))

        # Re-normalize after safety guards
        total = sum(c.new_weight for c in calibrated)
        if total > 0:
            for c in calibrated:
                c.new_weight = c.new_weight / total

        return calibrated

    def get_current_weights(self) -> dict[str, float]:
        """Get current signal weights."""
        return dict(self._current_weights)


# Constants
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.40
