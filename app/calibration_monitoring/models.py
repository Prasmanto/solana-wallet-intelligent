"""Calibration models for monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CalibrationSnapshot:
    """Snapshot of calibration state at a point in time."""
    id: str
    created_at: str
    signal_weights: dict[str, float]
    confidence_scaling: dict[str, float]
    regime_adjustments: dict[str, float]
    engine_adjustments: dict[str, float]


@dataclass
class WeightDrift:
    """Weight drift information."""
    signal_name: str
    current_value: float
    previous_value: float
    daily_change: float
    weekly_change: float
    status: str  # STABLE, WARNING, UNSTABLE


@dataclass
class VolatilityInfo:
    """Volatility information for a metric."""
    metric_name: str
    current_value: float
    standard_deviation: float
    ema_deviation: float
    max_swing: float
    status: str  # STABLE, WARNING, UNSTABLE


@dataclass
class ConvergenceInfo:
    """Convergence information for calibration."""
    metric_name: str
    is_converging: bool
    convergence_rate: float
    oscillation_detected: bool
    recent_values: list[float]


@dataclass
class CalibrationHealthReport:
    """Complete calibration health report."""
    health_score: float
    readiness_score: float
    weight_stability: float
    convergence_score: float
    volatility_score: float
    drift_score: float
    weight_drifts: list[WeightDrift]
    volatility_info: list[VolatilityInfo]
    convergence_info: list[ConvergenceInfo]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
