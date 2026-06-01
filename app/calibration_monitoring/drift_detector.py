"""Drift detector — detects calibration drift over time."""

from __future__ import annotations

from typing import Any

import structlog

from app.calibration_monitoring.models import CalibrationSnapshot, WeightDrift

logger = structlog.get_logger(__name__)


class DriftDetector:
    """Detects calibration drift over time."""

    def __init__(self) -> None:
        self._snapshots: list[CalibrationSnapshot] = []

    def record_snapshot(self, snapshot: CalibrationSnapshot) -> None:
        """Record a calibration snapshot."""
        self._snapshots.append(snapshot)

    def detect_drift(self) -> list[WeightDrift]:
        """Detect weight drift across snapshots."""
        if len(self._snapshots) < 2:
            return []

        current = self._snapshots[-1]
        previous = self._snapshots[-2]

        drifts = []

        for signal_name, current_value in current.signal_weights.items():
            previous_value = previous.signal_weights.get(signal_name, current_value)

            daily_change = current_value - previous_value

            # Compute weekly change (average of last 7 snapshots or fewer)
            weekly_values = [
                s.signal_weights.get(signal_name, current_value)
                for s in self._snapshots[-7:]
            ]
            weekly_change = (weekly_values[-1] - weekly_values[0]) / max(len(weekly_values) - 1, 1)

            # Determine status
            if abs(daily_change) > 0.05 or abs(weekly_change) > 0.1:
                status = "UNSTABLE"
            elif abs(daily_change) > 0.02 or abs(weekly_change) > 0.05:
                status = "WARNING"
            else:
                status = "STABLE"

            drifts.append(WeightDrift(
                signal_name=signal_name,
                current_value=current_value,
                previous_value=previous_value,
                daily_change=float(daily_change),
                weekly_change=float(weekly_change),
                status=status,
            ))

        return drifts

    def detect_slow_drift(self) -> dict[str, Any]:
        """Detect slow drift in calibration."""
        if len(self._snapshots) < 5:
            return {"drift_detected": False, "reason": "insufficient_data"}

        # Compare first and last snapshots
        first = self._snapshots[0]
        last = self._snapshots[-1]

        total_changes = []
        for signal_name, last_value in last.signal_weights.items():
            first_value = first.signal_weights.get(signal_name, last_value)
            change = last_value - first_value
            total_changes.append(abs(change))

        avg_change = sum(total_changes) / len(total_changes) if total_changes else 0

        return {
            "drift_detected": avg_change > 0.1,
            "average_change": float(avg_change),
            "snapshots_compared": len(self._snapshots),
        }

    def get_drift_history(self, limit: int = 10) -> list[WeightDrift]:
        """Get recent drift history."""
        if len(self._snapshots) < 2:
            return []
        return self.detect_drift()
