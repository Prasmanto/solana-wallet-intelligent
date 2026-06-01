"""Learning models — dataclasses for adaptive learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SignalReliability:
    """Reliability score for a signal."""
    signal_name: str
    success_rate: float
    return_quality: float
    sample_size: int
    stability: float
    reliability_score: float
    last_updated: str = ""

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class WeightAdjustment:
    """Record of a weight adjustment."""
    signal_name: str
    old_weight: float
    new_weight: float
    adjustment_pct: float
    reason: str
    metrics_used: dict[str, Any]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class LearningCycle:
    """Record of a learning cycle."""
    cycle_id: str
    signals_adjusted: int
    total_signals: int
    adaptation_rate: float
    weight_stability: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
