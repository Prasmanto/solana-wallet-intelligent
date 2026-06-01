"""Position models — dataclasses for paper trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PaperPosition:
    """Virtual position in paper trading."""
    position_id: str
    token: str
    entry_price: float
    quantity: float
    prediction_score: float
    confidence: float
    regime: str
    signal_breakdown: dict[str, float]
    cluster_id: str
    smart_money_present: bool
    entry_time: str
    status: str = "OPEN"
    exit_price: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""
    current_price: float = 0.0
    return_pct: float = 0.0
    max_return: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class PaperTradeOutcome:
    """Outcome of a closed paper trade."""
    position_id: str
    token: str
    entry_time: str
    exit_time: str
    holding_period_hours: float
    entry_price: float
    exit_price: float
    quantity: float
    roi: float
    max_roi: float
    max_drawdown: float
    win_loss: str
    exit_reason: str
    signal_attribution: dict[str, float]


@dataclass
class PortfolioSnapshot:
    """Portfolio state at a point in time."""
    timestamp: str
    total_value: float
    cash: float
    open_positions: int
    closed_positions: int
    total_pnl: float
    daily_pnl: float
    win_rate: float
