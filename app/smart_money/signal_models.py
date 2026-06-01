"""Signal models — standardized signal output schema.

All smart money signals follow this structure for consistency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SmartMoneySignal:
    """Standardized smart money signal output."""

    entity: str  # wallet or cluster_id
    entity_type: str  # "wallet" or "cluster"
    signal: str  # signal type
    score: float  # 0.0 - 1.0
    alpha_strength: str  # "LOW", "MEDIUM", "HIGH"
    recommendation: str  # "WATCH", "ACCUMULATE", "ALERT"
    confidence: float  # 0.0 - 1.0
    signals: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    correlation_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "entity": self.entity,
            "entity_type": self.entity_type,
            "signal": self.signal,
            "score": self.score,
            "alpha_strength": self.alpha_strength,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "signals": self.signals,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmartMoneySignal:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class VelocitySignal:
    """Velocity spike detection signal."""

    wallet: str
    velocity_ratio: float  # tx_5m / tx_1h
    tx_5m: int
    tx_1h: int
    baseline: int
    volume_increase: float  # volume_5m / volume_1h
    score: float
    confidence: float
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "signal": "VELOCITY_SPIKE",
            "velocity_ratio": self.velocity_ratio,
            "tx_5m": self.tx_5m,
            "tx_1h": self.tx_1h,
            "baseline": self.baseline,
            "volume_increase": self.volume_increase,
            "score": self.score,
            "confidence": self.confidence,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class LiquiditySignal:
    """Liquidity flow accumulation signal."""

    wallet: str
    net_flow: float
    inflow: float
    outflow: float
    flow_ratio: float
    sustained_windows: int
    score: float
    confidence: float
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "signal": "LIQUIDITY_ACCUMULATION",
            "net_flow": self.net_flow,
            "inflow": self.inflow,
            "outflow": self.outflow,
            "flow_ratio": self.flow_ratio,
            "sustained_windows": self.sustained_windows,
            "score": self.score,
            "confidence": self.confidence,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class ClusterSignal:
    """Cluster-level coordinated activity signal."""

    cluster_id: str
    active_wallets: int
    total_wallets: int
    synchronized_score: float
    velocity_score: float
    flow_score: float
    score: float
    confidence: float
    wallets: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "signal": "CLUSTER_ACCUMULATION",
            "active_wallets": self.active_wallets,
            "total_wallets": self.total_wallets,
            "synchronized_score": self.synchronized_score,
            "velocity_score": self.velocity_score,
            "flow_score": self.flow_score,
            "score": self.score,
            "confidence": self.confidence,
            "wallets": self.wallets,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


# Score level thresholds
SCORE_THRESHOLDS = {
    "noise": (0.0, 0.5),
    "weak": (0.5, 0.7),
    "medium": (0.7, 0.85),
    "strong": (0.85, 1.0),
}

RECOMMENDATION_THRESHOLDS = {
    "WATCH": (0.5, 0.7),
    "ACCUMULATE": (0.7, 0.85),
    "ALERT": (0.85, 1.0),
}


def get_alpha_strength(score: float) -> str:
    """Get alpha strength level from score."""
    if score < 0.5:
        return "LOW"
    elif score < 0.7:
        return "WEAK"
    elif score < 0.85:
        return "MEDIUM"
    else:
        return "HIGH"


def get_recommendation(score: float) -> str:
    """Get recommendation from score."""
    if score < 0.5:
        return "NOISE"
    elif score < 0.7:
        return "WATCH"
    elif score < 0.85:
        return "ACCUMULATE"
    else:
        return "ALERT"
