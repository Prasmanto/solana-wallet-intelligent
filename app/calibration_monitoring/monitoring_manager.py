"""Monitoring manager — orchestrates calibration monitoring."""

from __future__ import annotations

from typing import Any

import structlog

from app.calibration_monitoring.models import CalibrationSnapshot, CalibrationHealthReport
from app.calibration_monitoring.stability_tracker import StabilityTracker
from app.calibration_monitoring.drift_detector import DriftDetector
from app.calibration_monitoring.volatility_monitor import VolatilityMonitor
from app.calibration_monitoring.convergence_analyzer import ConvergenceAnalyzer

logger = structlog.get_logger(__name__)


class CalibrationMonitoringManager:
    """Orchestrates calibration monitoring."""

    def __init__(self) -> None:
        self._stability = StabilityTracker()
        self._drift = DriftDetector()
        self._volatility = VolatilityMonitor()
        self._convergence = ConvergenceAnalyzer()

    def record_snapshot(
        self,
        snapshot: CalibrationSnapshot,
    ) -> None:
        """Record a calibration snapshot to all monitors."""
        self._stability.record_snapshot(snapshot)
        self._drift.record_snapshot(snapshot)
        self._volatility.record_snapshot(snapshot)
        self._convergence.record_snapshot(snapshot)

    def compute_health_report(self) -> CalibrationHealthReport:
        """Compute calibration health report."""
        # Compute individual metrics
        stability = self._stability.compute_stability()
        weight_stability = stability.get("weight_stability", 0.5)

        drifts = self._drift.detect_drift()
        volatility_info = self._volatility.compute_volatility()
        convergence_info = self._convergence.analyze_convergence()

        # Compute volatility score
        unstable_count = sum(1 for v in volatility_info if v.status == "UNSTABLE")
        warning_count = sum(1 for v in volatility_info if v.status == "WARNING")
        volatility_score = max(0.0, 1.0 - (unstable_count * 0.2 + warning_count * 0.1))

        # Compute convergence score
        converging = sum(1 for c in convergence_info if c.is_converging)
        convergence_score = converging / max(len(convergence_info), 1)

        # Compute drift score
        drift_score = 1.0
        for d in drifts:
            if d.status == "UNSTABLE":
                drift_score -= 0.2
            elif d.status == "WARNING":
                drift_score -= 0.1
        drift_score = max(0.0, drift_score)

        # Overall health score
        health_score = (
            0.35 * weight_stability +
            0.25 * convergence_score +
            0.25 * volatility_score +
            0.15 * drift_score
        )

        # Self-learning readiness score
        readiness_score = self._compute_readiness(
            weight_stability, convergence_score, volatility_score, drift_score
        )

        return CalibrationHealthReport(
            health_score=round(health_score, 4),
            readiness_score=round(readiness_score, 4),
            weight_stability=round(weight_stability, 4),
            convergence_score=round(convergence_score, 4),
            volatility_score=round(volatility_score, 4),
            drift_score=round(drift_score, 4),
            weight_drifts=drifts,
            volatility_info=volatility_info,
            convergence_info=convergence_info,
        )

    def _compute_readiness(
        self,
        weight_stability: float,
        convergence: float,
        volatility: float,
        drift: float,
    ) -> float:
        """Compute self-learning readiness score."""
        # Requirements for readiness:
        # - Stable calibration (weight_stability > 0.7)
        # - Low volatility (volatility > 0.7)
        # - High convergence (convergence > 0.6)
        # - Low drift (drift > 0.7)

        readiness = (
            0.35 * weight_stability +
            0.25 * convergence +
            0.20 * volatility +
            0.20 * drift
        )

        return max(0.0, min(1.0, readiness))

    def get_readiness_status(self) -> str:
        """Get self-learning readiness status."""
        report = self.compute_health_report()
        if report.readiness_score >= 0.7:
            return "READY"
        elif report.readiness_score >= 0.5:
            return "CONDITIONAL"
        else:
            return "NOT_READY"
