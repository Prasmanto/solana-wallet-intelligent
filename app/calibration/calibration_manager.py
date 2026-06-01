"""Calibration manager — orchestrates calibration cycles."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.calibration.calibration_models import CalibrationReport
from app.calibration.signal_calibrator import SignalCalibrator
from app.calibration.confidence_calibrator import ConfidenceCalibrator
from app.calibration.regime_calibrator import RegimeCalibrator
from app.calibration.engine_calibrator import EngineCalibrator

logger = structlog.get_logger(__name__)


class CalibrationManager:
    """Orchestrates calibration cycles."""

    def __init__(self) -> None:
        self._signal_calibrator = SignalCalibrator()
        self._confidence_calibrator = ConfidenceCalibrator()
        self._regime_calibrator = RegimeCalibrator()
        self._engine_calibrator = EngineCalibrator()
        self._calibration_history: list[CalibrationReport] = []

    async def run_calibration(
        self,
        signal_attribution: dict[str, dict[str, Any]],
        confidence_analysis: dict[str, dict[str, Any]],
        regime_performance: dict[str, dict[str, Any]],
        engine_performance: dict[str, dict[str, Any]],
    ) -> CalibrationReport:
        """Run a full calibration cycle."""
        # 1. Calibrate signals
        signal_weights = self._signal_calibrator.calibrate(signal_attribution)

        # 2. Calibrate confidence
        confidence_scaling = self._confidence_calibrator.calibrate(confidence_analysis)

        # 3. Calibrate regimes
        regime_adjustments = self._regime_calibrator.calibrate(regime_performance)

        # 4. Calibrate engines
        engine_adjustments = self._engine_calibrator.calibrate(engine_performance)

        # Build report
        report = CalibrationReport(
            signal_weights=signal_weights,
            confidence_scaling=confidence_scaling,
            regime_adjustments=regime_adjustments,
            engine_adjustments=engine_adjustments,
            total_signals=len(signal_weights),
            total_engines=len(engine_adjustments),
        )

        # Store in history
        self._calibration_history.append(report)

        logger.info(
            "calibration.completed",
            signals=len(signal_weights),
            confidence_buckets=len(confidence_scaling),
            regimes=len(regime_adjustments),
            engines=len(engine_adjustments),
        )

        return report

    def get_current_weights(self) -> dict[str, float]:
        """Get current signal weights."""
        return self._signal_calibrator.get_current_weights()

    def get_calibration_curve(self) -> dict[str, float]:
        """Get current confidence calibration curve."""
        return self._confidence_calibrator.get_calibration_curve()

    def get_regime_multipliers(self) -> dict[str, float]:
        """Get current regime multipliers."""
        return self._regime_calibrator.get_current_multipliers()

    def get_engine_reliability(self) -> dict[str, float]:
        """Get current engine reliability scores."""
        return self._engine_calibrator.get_reliability_scores()

    def get_history(self, limit: int = 10) -> list[CalibrationReport]:
        """Get calibration history."""
        return self._calibration_history[-limit:]
