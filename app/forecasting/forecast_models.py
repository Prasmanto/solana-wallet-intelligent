"""Forecast models — reusable dataclasses for forecasting outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ClusterEnergySnapshot:
    """Energy state of a cluster."""
    cluster_id: str
    energy_score: float
    trend: str  # "rising", "stable", "decaying"
    smart_money_density: float
    liquidity_pressure: float
    momentum_score: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class CapitalRotationSignal:
    """Capital flow between clusters."""
    source_cluster: str
    target_cluster: str
    rotation_strength: float
    confidence: float
    smart_money_moving: bool
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ClusterForecast:
    """Forecast for a cluster's future state."""
    cluster_id: str
    forecast_score: float
    confidence: float
    expected_time_horizon: str  # "15m", "1h", "4h"
    contributing_factors: list[str]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class FutureLeaderPrediction:
    """Prediction of next leader token."""
    current_leader: str
    predicted_next_leader: str
    probability: float
    eta_minutes: int
    emerging_tokens: list[str]
    fading_tokens: list[str]
    cluster_id: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ForecastResult:
    """Complete forecasting output."""
    cluster_energy: list[ClusterEnergySnapshot]
    capital_rotations: list[CapitalRotationSignal]
    cluster_forecasts: list[ClusterForecast]
    leader_predictions: list[FutureLeaderPrediction]
    forecast_score: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_energy": [vars(c) for c in self.cluster_energy],
            "capital_rotations": [vars(r) for r in self.capital_rotations],
            "cluster_forecasts": [vars(f) for f in self.cluster_forecasts],
            "leader_predictions": [vars(p) for p in self.leader_predictions],
            "forecast_score": round(self.forecast_score, 4),
            "timestamp": self.timestamp,
        }
