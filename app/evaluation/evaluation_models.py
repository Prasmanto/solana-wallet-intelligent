"""Evaluation models — dataclasses for prediction tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PredictionRecord:
    """Stored prediction record."""
    id: str
    prediction_type: str  # "pump", "cluster", "leader"
    token: str
    cluster_id: str
    predicted_score: float
    predicted_probability: float
    predicted_eta_minutes: int
    prediction_horizon: str  # "15m", "1h", "4h"
    status: str  # "PENDING", "RESOLVED", "EXPIRED"
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionOutcome:
    """Outcome of a resolved prediction."""
    prediction_id: str
    resolved_at: str
    price_change_15m: float
    price_change_1h: float
    price_change_4h: float
    volume_change: float
    success: bool
    failure: bool
    outcome_score: float


@dataclass
class PredictionScorecard:
    """Complete scorecard for a resolved prediction."""
    prediction: PredictionRecord
    outcome: PredictionOutcome | None = None
    accuracy: float = 0.0
    expected_return: float = 0.0
    actual_return: float = 0.0


@dataclass
class EvaluationMetrics:
    """Aggregated evaluation metrics."""
    overall_accuracy: float
    accuracy_15m: float
    accuracy_1h: float
    accuracy_4h: float
    total_predictions: int
    resolved_predictions: int
    precision: float
    recall: float
    win_rate: float
    average_return: float
    confidence_calibration: dict[str, float]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
