"""Calibration models — dataclasses for calibration outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SignalCalibration:
    """Calibrated signal weights."""
    signal_name: str
    old_weight: float
    new_weight: float
    success_rate: float
    average_return: float
    confidence: float


@dataclass
class ConfidenceCalibration:
    """Calibrated confidence scaling."""
    raw_confidence: float
    calibrated_confidence: float
    actual_success_rate: float
    calibration_error: float


@dataclass
class RegimeCalibration:
    """Calibrated regime multipliers."""
    regime: str
    old_multiplier: float
    new_multiplier: float
    accuracy: float


@dataclass
class EngineCalibration:
    """Calibrated engine reliability scores."""
    engine_name: str
    reliability_score: float
    accuracy: float
    average_return: float


@dataclass
class CalibrationReport:
    """Complete calibration report."""
    signal_weights: list[SignalCalibration]
    confidence_scaling: list[ConfidenceCalibration]
    regime_adjustments: list[RegimeCalibration]
    engine_adjustments: list[EngineCalibration]
    timestamp: str = ""
    total_signals: int = 0
    total_engines: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_weights": [vars(s) for s in self.signal_weights],
            "confidence_scaling": [vars(c) for c in self.confidence_scaling],
            "regime_adjustments": [vars(r) for r in self.regime_adjustments],
            "engine_adjustments": [vars(e) for e in self.engine_adjustments],
            "timestamp": self.timestamp,
        }
