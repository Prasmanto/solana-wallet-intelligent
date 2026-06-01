"""Stability tracker — tracks calibration stability over time."""

from __future__ import annotations

import statistics
from typing import Any

import structlog

from app.calibration_monitoring.models import CalibrationSnapshot, CalibrationHealthReport

logger = structlog.get_logger(__name__)


class StabilityTracker:
    """Tracks calibration stability over time."""

    def __init__(self) -> None:
        self._snapshots: list[CalibrationSnapshot] = []

    def record_snapshot(self, snapshot: CalibrationSnapshot) -> None:
        """Record a calibration snapshot."""
        self._snapshots.append(snapshot)
        # Keep last 100 snapshots
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-100:]

    def compute_stability(self) -> dict[str, Any]:
        """Compute stability metrics."""
        if len(self._snapshots) < 2:
            return {"stable": True, "reason": "insufficient_data"}

        # Get recent snapshots
        recent = self._snapshots[-10:]

        # Compute weight stability
        weight_stability = self._compute_weight_stability(recent)

        return {
            "total_snapshots": len(self._snapshots),
            "recent_snapshots": len(recent),
            "weight_stability": weight_stability,
            "is_stable": weight_stability > 0.7,
        }

    def _compute_weight_stability(self, snapshots: list[CalibrationSnapshot]) -> float:
        """Compute weight stability score."""
        if len(snapshots) < 2:
            return 1.0

        # Collect all weight histories
        all_weights: dict[str, list[float]] = {}
        for snap in snapshots:
            for name, value in snap.signal_weights.items():
                if name not in all_weights:
                    all_weights[name] = []
                all_weights[name].append(value)

        # Compute average coefficient of variation
        cvs = []
        for name, weights in all_weights.items():
            if len(weights) < 2:
                continue
            mean = statistics.mean(weights)
            if mean == 0:
                continue
            stdev = statistics.stdev(weights)
            cv = stdev / abs(mean)
            cvs.append(cv)

        if not cvs:
            return 1.0

        avg_cv = statistics.mean(cvs)

        # Lower CV = more stable
        # CV < 0.05 = very stable, CV > 0.2 = unstable
        stability = max(0.0, min(1.0, 1.0 - avg_cv * 5))

        return stability

    def get_snapshot_history(self, limit: int = 10) -> list[CalibrationSnapshot]:
        """Get recent calibration snapshots."""
        return self._snapshots[-limit:]
