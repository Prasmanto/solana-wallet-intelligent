"""Convergence analyzer — detects calibration convergence."""

from __future__ import annotations

import statistics
from typing import Any

import structlog

from app.calibration_monitoring.models import CalibrationSnapshot, ConvergenceInfo

logger = structlog.get_logger(__name__)


class ConvergenceAnalyzer:
    """Analyzes whether calibration is converging."""

    def __init__(self) -> None:
        self._snapshots: list[CalibrationSnapshot] = []

    def record_snapshot(self, snapshot: CalibrationSnapshot) -> None:
        """Record a calibration snapshot."""
        self._snapshots.append(snapshot)

    def analyze_convergence(self) -> list[ConvergenceInfo]:
        """Analyze convergence for each signal weight."""
        if len(self._snapshots) < 3:
            return []

        results = []

        # Get all signal names
        all_signals = set()
        for snap in self._snapshots:
            all_signals.update(snap.signal_weights.keys())

        for signal_name in all_signals:
            values = [
                snap.signal_weights.get(signal_name, 0.0)
                for snap in self._snapshots[-10:]  # Last 10 snapshots
            ]

            if len(values) < 3:
                continue

            # Check convergence (variance decreasing)
            first_half = values[:len(values)//2]
            second_half = values[len(values)//2:]

            first_var = statistics.variance(first_half) if len(first_half) > 1 else 0
            second_var = statistics.variance(second_half) if len(second_half) > 1 else 0

            is_converging = second_var < first_var

            # Check for oscillation
            signs = [values[i+1] - values[i] for i in range(len(values)-1)]
            sign_changes = sum(1 for i in range(len(signs)-1) if signs[i] * signs[i+1] < 0)
            oscillation = sign_changes > len(signs) * 0.5

            # Convergence rate
            if len(values) >= 3:
                recent_change = abs(values[-1] - values[-3])
                convergence_rate = 1.0 - min(1.0, recent_change)
            else:
                convergence_rate = 0.5

            results.append(ConvergenceInfo(
                metric_name=signal_name,
                is_converging=is_converging and not oscillation,
                convergence_rate=convergence_rate,
                oscillation_detected=oscillation,
                recent_values=values,
            ))

        return results

    def get_overall_convergence(self) -> float:
        """Get overall convergence score."""
        results = self.analyze_convergence()
        if not results:
            return 0.5

        converging_count = sum(1 for r in results if r.is_converging)
        return converging_count / len(results) if results else 0.5
