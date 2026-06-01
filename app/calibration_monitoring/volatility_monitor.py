"""Volatility monitor — monitors calibration volatility."""

from __future__ import annotations

import statistics
from typing import Any

import structlog

from app.calibration_monitoring.models import CalibrationSnapshot, VolatilityInfo

logger = structlog.get_logger(__name__)


class VolatilityMonitor:
    """Monitors calibration volatility."""

    def __init__(self) -> None:
        self._snapshots: list[CalibrationSnapshot] = []

    def record_snapshot(self, snapshot: CalibrationSnapshot) -> None:
        """Record a calibration snapshot."""
        self._snapshots.append(snapshot)

    def compute_volatility(self) -> list[VolatilityInfo]:
        """Compute volatility for each signal weight."""
        if len(self._snapshots) < 2:
            return []

        volatilities = []

        # Get all signal names
        all_signals = set()
        for snap in self._snapshots:
            all_signals.update(snap.signal_weights.keys())

        for signal_name in all_signals:
            values = [
                snap.signal_weights.get(signal_name, 0.0)
                for snap in self._snapshots
            ]

            if len(values) < 2:
                continue

            # Standard deviation
            stdev = statistics.stdev(values) if len(values) > 1 else 0.0

            # EMA deviation
            ema_dev = self._compute_ema_deviation(values)

            # Max swing
            max_swing = max(values) - min(values)

            # Current value
            current = values[-1]

            # Determine status
            if stdev > 0.1 or max_swing > 0.2:
                status = "UNSTABLE"
            elif stdev > 0.05 or max_swing > 0.1:
                status = "WARNING"
            else:
                status = "STABLE"

            volatilities.append(VolatilityInfo(
                metric_name=signal_name,
                current_value=current,
                standard_deviation=stdev,
                ema_deviation=ema_dev,
                max_swing=float(max_swing),
                status=status,
            ))

        return volatilities

    def _compute_ema_deviation(self, values: list[float]) -> float:
        """Compute EMA-based deviation."""
        if len(values) < 2:
            return 0.0

        alpha = 0.3  # EMA smoothing factor
        ema = values[0]
        deviations = []

        for v in values[1:]:
            ema = alpha * v + (1 - alpha) * ema
            deviation = abs(v - ema)
            deviations.append(deviation)

        return sum(deviations) / len(deviations) if deviations else 0.0

    def get_volatility_status(self) -> str:
        """Get overall volatility status."""
        volatilities = self.compute_volatility()
        if not volatilities:
            return "STABLE"

        unstable_count = sum(1 for v in volatilities if v.status == "UNSTABLE")
        warning_count = sum(1 for v in volatilities if v.status == "WARNING")

        if unstable_count > 2:
            return "UNSTABLE"
        elif warning_count > 3:
            return "WARNING"
        return "STABLE"
