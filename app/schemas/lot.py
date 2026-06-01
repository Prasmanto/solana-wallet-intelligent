"""Lot schemas — Pydantic models for FIFO lot information."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class LotStatus(str, Enum):
    """Lot lifecycle status."""

    OPEN = "open"          # Fully available
    PARTIAL = "partial"    # Partially consumed
    CLOSED = "closed"      # Fully consumed


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
