"""Wallet metrics schema — Pydantic models for aggregated wallet intelligence.

Defines:
- WalletMetrics: aggregated metrics for a wallet
- TokenMetrics: per-token metrics
- TradeSummary: summary of a single trade's impact
- AggregationResult: result of metrics aggregation
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class WalletMetrics(BaseModel):
    """Aggregated metrics for a wallet across all tokens."""

    wallet: str

    # ── PnL Metrics ─────────────────────────────────────────
    total_realized_pnl: Decimal = Decimal("0")
    total_realized_roi: Decimal = Decimal("0")
    total_fees_paid: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")

    # ── Win/Loss Metrics ────────────────────────────────────
    total_wins: int = 0
    total_losses: int = 0
    win_rate: Decimal = Decimal("0")
    avg_win_pnl: Decimal = Decimal("0")
    avg_loss_pnl: Decimal = Decimal("0")
    best_trade_pnl: Decimal = Decimal("0")
    worst_trade_pnl: Decimal = Decimal("0")
    best_trade_token: str = ""
    worst_trade_token: str = ""

    # ── Position Metrics ────────────────────────────────────
    total_unique_tokens: int = 0
    active_positions: int = 0
    total_trades: int = 0
    total_buys: int = 0
    total_sells: int = 0

    # ── Volume Metrics ──────────────────────────────────────
    total_buy_volume: Decimal = Decimal("0")
    total_sell_volume: Decimal = Decimal("0")
    total_volume: Decimal = Decimal("0")

    # ── Hold Duration ───────────────────────────────────────
    avg_hold_duration_seconds: int = 0
    avg_hold_duration_human: str = ""

    # ── Position Size ───────────────────────────────────────
    avg_position_size: Decimal = Decimal("0")
    max_position_size: Decimal = Decimal("0")

    # ── Timestamps ──────────────────────────────────────────
    first_trade_at: datetime | None = None
    last_trade_at: datetime | None = None
    last_updated_at: datetime | None = None

    # ── Versioning ──────────────────────────────────────────
    metrics_version: int = 1
    last_trade_id: str = ""

    # ── Metadata ────────────────────────────────────────────
    computed_at: datetime | None = None


class TokenMetrics(BaseModel):
    """Per-token metrics for a wallet."""

    wallet: str
    token_mint: str

    # ── Position State ──────────────────────────────────────
    position_size: Decimal = Decimal("0")
    avg_cost_basis: Decimal = Decimal("0")
    total_cost_basis: Decimal = Decimal("0")

    # ── PnL ─────────────────────────────────────────────────
    realized_pnl: Decimal = Decimal("0")
    realized_roi: Decimal = Decimal("0")

    # ── Trade Stats ─────────────────────────────────────────
    total_buys: int = 0
    total_sells: int = 0
    total_buy_volume: Decimal = Decimal("0")
    total_sell_volume: Decimal = Decimal("0")

    # ── Timing ──────────────────────────────────────────────
    first_buy_at: datetime | None = None
    last_trade_at: datetime | None = None
    hold_duration_seconds: int = 0

    # ── Fees ────────────────────────────────────────────────
    total_fees_paid: Decimal = Decimal("0")


class TradeSummary(BaseModel):
    """Summary of a single trade's impact on metrics."""

    trade_id: str
    wallet: str
    token_mint: str
    direction: str
    quantity: Decimal
    price: Decimal
    total_value: Decimal
    realized_pnl: Decimal | None = None
    fees: Decimal = Decimal("0")
    timestamp: datetime


class AggregationResult(BaseModel):
    """Result of a wallet metrics aggregation."""

    wallet: str
    metrics: WalletMetrics
    token_metrics: list[TokenMetrics]
    trades_processed: int
    aggregation_time_ms: float
    computed_at: datetime
