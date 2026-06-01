"""Regime calibrator — adjusts regime multipliers based on performance."""

from __future__ import annotations

from typing import Any

import structlog

from app.calibration.calibration_models import RegimeCalibration

logger = structlog.get_logger(__name__)

MAX_REGIME_CHANGE = 0.15


class RegimeCalibrator:
    """Calibrates regime multipliers based on historical accuracy."""

    def __init__(self) -> None:
        self._current_multipliers: dict[str, float] = {
            "NORMAL": 1.0,
            "ACCUMULATION": 1.2,
            "PUMP_BUILDUP": 1.35,
            "PARABOLIC": 1.6,
        }

    def calibrate(
        self,
        regime_performance: dict[str, dict[str, Any]],
    ) -> list[RegimeCalibration]:
        """Calibrate regime multipliers based on performance."""
        calibrated = []

        for regime, old_multiplier in self._current_multipliers.items():
            stats = regime_performance.get(regime, {})
            accuracy = stats.get("accuracy", 0.5)

            # Compute new multiplier based on accuracy
            new_multiplier = self._compute_multiplier(old_multiplier, accuracy)

            calibrated.append(RegimeCalibration(
                regime=regime,
                old_multiplier=old_multiplier,
                new_multiplier=new_multiplier,
                accuracy=accuracy,
            ))

        # Apply safety guards
        calibrated = self._apply_safety_guards(calibrated)

        # Update current multipliers
        for reg in calibrated:
            self._current_multipliers[reg.regime] = reg.new_multiplier

        return calibrated

    def _compute_multiplier(
        self,
        old_multiplier: float,
        accuracy: float,
    ) -> float:
        """Compute new multiplier based on accuracy."""
        # Higher accuracy = higher multiplier
        # Base multiplier range: 0.5 - 2.0
        base = 0.5 + (accuracy * 1.5)

        # EMA smoothing
        smoothed = 0.7 * old_multiplier + 0.3 * base

        return float(max(0.5, min(2.0, smoothed)))

    def _apply_safety_guards(
        self,
        calibrated: list[RegimeCalibration],
    ) -> list[RegimeCalibration]:
        """Apply safety guards to prevent extreme changes."""
        for reg in calibrated:
            # Limit multiplier change
            change = abs(reg.new_multiplier - reg.old_multiplier)
            if change > MAX_REGIME_CHANGE:
                if reg.new_multiplier > reg.old_multiplier:
                    reg.new_multiplier = reg.old_multiplier + MAX_REGIME_CHANGE
                else:
                    reg.new_multiplier = reg.old_multiplier - MAX_REGIME_CHANGE

            # Enforce bounds
            reg.new_multiplier = max(0.5, min(2.0, reg.new_multiplier))

        return calibrated

    def get_current_multipliers(self) -> dict[str, float]:
        """Get current regime multipliers."""
        return dict(self._current_multipliers)


MAX_REGIME_CHANGE = 0.15
