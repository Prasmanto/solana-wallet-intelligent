"""Engine calibrator — generates reliability scores for prediction engines."""

from __future__ import annotations

from typing import Any

import structlog

from app.calibration.calibration_models import EngineCalibration

logger = structlog.get_logger(__name__)


class EngineCalibrator:
    """Calibrates engine reliability scores based on performance."""

    def __init__(self) -> None:
        self._engine_reliability: dict[str, float] = {
            "pump": 1.0,
            "leader": 0.8,
            "cluster": 0.85,
            "ranking": 0.9,
        }

    def calibrate(
        self,
        engine_performance: dict[str, dict[str, Any]],
    ) -> list[EngineCalibration]:
        """Calibrate engine reliability scores."""
        calibrated = []

        for engine_name, old_reliability in self._engine_reliability.items():
            stats = engine_performance.get(engine_name, {})
            accuracy = stats.get("accuracy", 0.5)
            avg_return = stats.get("average_return", 0.0)

            # Compute reliability score
            reliability = self._compute_reliability(accuracy, avg_return)

            calibrated.append(EngineCalibration(
                engine_name=engine_name,
                reliability_score=reliability,
                accuracy=accuracy,
                average_return=avg_return,
            ))

        # Apply safety guards
        calibrated = self._apply_safety_guards(calibrated)

        # Update current reliability
        for eng in calibrated:
            self._engine_reliability[eng.engine_name] = eng.reliability_score

        return calibrated

    def _compute_reliability(
        self,
        accuracy: float,
        avg_return: float,
    ) -> float:
        """Compute reliability score."""
        # Reliability = accuracy * (1 + min(avg_return/100, 0.5))
        return float(max(0.0, min(1.0, accuracy * (1 + min(avg_return / 100, 0.5)))))

    def _apply_safety_guards(
        self,
        calibrated: list[EngineCalibration],
    ) -> list[EngineCalibration]:
        """Apply safety guards."""
        for eng in calibrated:
            # Limit reliability change
            old = self._engine_reliability.get(eng.engine_name, 0.8)
            change = abs(eng.reliability_score - old)
            if change > 0.20:
                if eng.reliability_score > old:
                    eng.reliability_score = old + 0.20
                else:
                    eng.reliability_score = old - 0.20

            # EMA smoothing
            smoothed = 0.7 * old + 0.3 * eng.reliability_score
            eng.reliability_score = float(max(0.0, min(1.0, smoothed)))

        return calibrated

    def get_reliability_scores(self) -> dict[str, float]:
        """Get current reliability scores."""
        return dict(self._engine_reliability)
