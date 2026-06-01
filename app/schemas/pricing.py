"""Pricing schemas — Pydantic models for token pricing and valuation.

Defines:
- TokenPrice: current token price data
- PriceSnapshot: point-in-time price snapshot
- PositionValuation: unrealized PnL for a position
- WalletValuation: total wallet valuation
- PricingResult: result of pricing operation
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class TokenPrice(BaseModel):
    """Current token price data from Jupiter."""

    mint: str
    price: Decimal
    symbol: str = ""
    name: str = ""
    decimals: int = 9
    confidence: Decimal = Decimal("1.0")  # 0.0 to 1.0
    source: str = "jupiter"
    fetched_at: datetime

    @property
    def is_stale(self) -> bool:
        """Check if price is older than 5 minutes."""
        from datetime import timezone
        age = datetime.now(timezone.utc) - self.fetched_at
        return age.total_seconds() > 300  # 5 minutes

    @property
    def price_age_seconds(self) -> float:
        """Get price age in seconds."""
        from datetime import timezone
        age = datetime.now(timezone.utc) - self.fetched_at
        return age.total_seconds()


class PriceSnapshot(BaseModel):
    """Point-in-time price snapshot for storage."""

    mint: str
    price: Decimal
    source: str
    fetched_at: datetime
    slot: int | None = None
    confidence: Decimal = Decimal("1.0")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionValuation(BaseModel):
    """Unrealized PnL and valuation for a single position."""

    wallet: str
    token_mint: str

    # ── Position State ──────────────────────────────────────
    position_size: Decimal
    avg_cost_basis: Decimal
    total_cost_basis: Decimal

    # ── Current Market ──────────────────────────────────────
    current_price: Decimal
    market_value: Decimal
    price_age_seconds: float
    price_confidence: Decimal

    # ── Unrealized PnL ──────────────────────────────────────
    unrealized_pnl: Decimal
    unrealized_roi: Decimal

    # ── Combined PnL ────────────────────────────────────────
    realized_pnl: Decimal
    total_pnl: Decimal
    total_roi: Decimal

    # ── Liquidity ───────────────────────────────────────────
    liquidity_confidence: Decimal = Decimal("1.0")
    is_illiquid: bool = False


class WalletValuation(BaseModel):
    """Total wallet valuation with all positions."""

    wallet: str

    # ── Position Valuations ─────────────────────────────────
    positions: list[PositionValuation]

    # ── Totals ──────────────────────────────────────────────
    total_market_value: Decimal = Decimal("0")
    total_cost_basis: Decimal = Decimal("0")
    total_unrealized_pnl: Decimal = Decimal("0")
    total_realized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    total_roi: Decimal = Decimal("0")

    # ── Liquidity Metrics ───────────────────────────────────
    liquidity_score: Decimal = Decimal("1.0")
    illiquid_positions: int = 0

    # ── Timestamps ──────────────────────────────────────────
    valued_at: datetime
    prices_fresh: bool = True


class PricingResult(BaseModel):
    """Result of a pricing operation."""

    success: bool
    prices_fetched: int = 0
    prices_stale: int = 0
    prices_missing: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0


class WalletRanking(BaseModel):
    """Wallet ranking metrics for leaderboard."""

    wallet: str
    rank: int = 0
    total_pnl: Decimal = Decimal("0")
    total_roi: Decimal = Decimal("0")
    win_rate: Decimal = Decimal("0")
    total_trades: int = 0
    total_volume: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    score: Decimal = Decimal("0")  # Composite ranking score
