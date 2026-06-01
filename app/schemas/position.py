"""Position schemas — Pydantic models for position state and PnL.

Defines:
- PositionState: current position state
- LotInfo: FIFO lot information
- RealizedPnLResult: PnL calculation result
- PositionUpdate: event for position updates
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LotStatus(str, Enum):
    """Lot lifecycle status."""

    OPEN = "open"          # Fully available
    PARTIAL = "partial"    # Partially consumed
    CLOSED = "closed"      # Fully consumed


class PositionState(BaseModel):
    """Current position state for a wallet + token pair."""

    wallet: str
    token_mint: str
    position_size: Decimal = Decimal("0")
    avg_cost_basis: Decimal = Decimal("0")
    total_cost_basis: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    realized_roi: Decimal = Decimal("0")
    total_buys: int = 0
    total_sells: int = 0
    total_buy_volume: Decimal = Decimal("0")
    total_sell_volume: Decimal = Decimal("0")
    total_fees_paid: Decimal = Decimal("0")
    first_buy_at: datetime | None = None
    last_buy_at: datetime | None = None
    first_sell_at: datetime | None = None
    last_sell_at: datetime | None = None
    last_trade_at: datetime | None = None
    hold_duration_seconds: int = 0
    last_trade_id: str = ""
    event_version: int = 0


class LotInfo(BaseModel):
    """FIFO lot information."""

    id: str
    wallet: str
    token_mint: str
    trade_id: str
    signature: str
    original_quantity: Decimal
    remaining_quantity: Decimal
    cost_basis_per_token: Decimal
    total_cost: Decimal
    status: LotStatus
    buy_timestamp: datetime
    closed_at: datetime | None = None

    @property
    def is_fully_consumed(self) -> bool:
        return self.remaining_quantity <= 0

    @property
    def consumption_ratio(self) -> float:
        """How much of this lot has been consumed (0.0 to 1.0)."""
        if self.original_quantity <= 0:
            return 1.0
        return float(1 - (self.remaining_quantity / self.original_quantity))


class RealizedPnLResult(BaseModel):
    """Result of a realized PnL calculation for a single sell."""

    trade_id: str
    wallet: str
    token_mint: str
    sell_quantity: Decimal
    sell_price: Decimal
    total_proceeds: Decimal
    total_cost: Decimal
    realized_pnl: Decimal
    realized_roi: Decimal
    lots_consumed: list[LotInfo]
    fees: Decimal = Decimal("0")


class PositionUpdate(BaseModel):
    """Event emitted when a position is updated."""

    wallet: str
    token_mint: str
    trade_id: str
    direction: str  # buy or sell
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    realized_pnl: Decimal | None = None
    new_position_size: Decimal = Decimal("0")
    new_avg_cost: Decimal = Decimal("0")


class PositionSnapshot(BaseModel):
    """Point-in-time snapshot of all positions for a wallet."""

    wallet: str
    positions: list[PositionState]
    total_realized_pnl: Decimal = Decimal("0")
    snapshot_at: datetime
