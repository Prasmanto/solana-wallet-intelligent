"""Confidence calibrator — adjusts confidence scaling based on calibration data."""

from __future__ import annotations

import math
from typing import Any

import structlog

from app.calibration.calibration_models import ConfidenceCalibration

logger = structlog.get_logger(__name__)

MAX_ADJUSTMENT = 0.15


class ConfidenceCalibrator:
    """Calibrates confidence scaling based on historical accuracy."""

    def __init__(self) -> None:
        self._calibration_curve: dict[str, float] = {
            "0.0-0.3": 0.5,
            "0.3-0.5": 0.7,
            "0.5-0.7": 0.85,
            "0.7-0.8": 0.95,
            "0.8-0.9": 0.90,
            "0.9-1.0": 0.80,
        }

    def calibrate(
        self,
        confidence_analysis: dict[str, dict[str, Any]],
    ) -> list[ConfidenceCalibration]:
        """Calibrate confidence scaling based on analysis data."""
        calibrated = []

        for bucket, stats in confidence_analysis.items():
            if stats.get("count", 0) == 0:
                continue

            raw_confidence = self._bucket_to_midpoint(bucket)
            actual_success_rate = stats.get("success_rate", 0.0)

            # Compute calibrated confidence
            calibrated_confidence = self._calibrate_confidence(
                raw_confidence, actual_success_rate
            )

            # Compute calibration error
            calibration_error = abs(calibrated_confidence - actual_success_rate)

            calibrated.append(ConfidenceCalibration(
                raw_confidence=raw_confidence,
                calibrated_confidence=calibrated_confidence,
                actual_success_rate=actual_success_rate,
                calibration_error=calibration_error,
            ))

        # Update calibration curve
        for c in calibrated:
            bucket = self._midpoint_to_bucket(c.raw_confidence)
            self._calibration_curve[bucket] = float(c.calibrated_confidence)

        return calibrated

    def _calibrate_confidence(
        self,
        raw_confidence: float,
        actual_success_rate: float,
    ) -> float:
        """Compute calibrated confidence."""
        # Adjust raw confidence based on actual success rate
        adjustment = actual_success_rate - raw_confidence

        # Apply adjustment with safety limit
        adjustment = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, adjustment))

        # EMA smoothing
        smoothed = 0.7 * raw_confidence + 0.3 * (raw_confidence + adjustment)

        return max(0.0, min(1.0, smoothed))

    def _bucket_to_midpoint(self, bucket: str) -> float:
        """Convert bucket label to midpoint value."""
        parts = bucket.split("-")
        if len(parts) == 2:
            low = float(parts[0])
            high = float(parts[1])
            return (low + high) / 2
        return 0.5

    def _midpoint_to_bucket(self, midpoint: float) -> str:
        """Convert midpoint to bucket label."""
        if midpoint < 0.3:
            return "0.0-0.3"
        elif midpoint < 0.5:
            return "0.3-0.5"
        elif midpoint < 0.7:
            return "0.5-0.7"
        elif midpoint < 0.8:
            return "0.7-0.8"
        elif midpoint < 0.9:
            return "0.8-0.9"
        else:
            return "0.9-1.0"

    def get_calibration_curve(self) -> dict[str, float]:
        """Get current calibration curve."""
        return dict(self._calibration_curve)

    def calibrate_single(self, raw_confidence: float) -> float:
        """Calibrate a single confidence value."""
        bucket = self._midpoint_to_bucket(raw_confidence)
        return self._calibration_curve.get(bucket, raw_confidence)


# Safety constants
MAX_ADJUSTMENT = 0.15
