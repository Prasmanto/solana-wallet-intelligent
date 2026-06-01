"""FIFO lot model — tracks individual buy lots for cost basis calculation.

Implements FIFO (First-In-First-Out) accounting:
- Each buy creates a lot with quantity and cost basis
- Each sell consumes lots in FIFO order
- Partial lot consumption is supported
- Lots are immutable once created

This enables accurate realized PnL calculation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class PositionLot(Base):
    """Individual buy lot for FIFO accounting.

    Created when a wallet buys a token.
    Consumed (partially or fully) when the wallet sells.
    """

    __tablename__ = "position_lots"

    # ── Primary Key ─────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── Identity ────────────────────────────────────────────
    wallet: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
        comment="Wallet address",
    )
    token_mint: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
        comment="Token mint address",
    )
    trade_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        comment="Trade ID that created this lot",
    )
    signature: Mapped[str] = mapped_column(
        String(88),
        nullable=False,
        comment="Transaction signature",
    )

    # ── Lot State ───────────────────────────────────────────
    original_quantity: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        comment="Original lot quantity",
    )
    remaining_quantity: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        comment="Remaining quantity (decreases on sell)",
    )
    cost_basis_per_token: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        comment="Cost basis per token (in quote currency)",
    )
    total_cost: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        comment="Total cost of this lot",
    )

    # ── Status ──────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="open",
        comment="Lot status: open | partial | closed",
    )

    # ── Timestamps ──────────────────────────────────────────
    buy_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the buy occurred",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this lot was created",
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this lot was fully consumed",
    )

    # ── Indexes ─────────────────────────────────────────────
    __table_args__ = (
        # Query lots for a wallet + token in FIFO order
        Index(
            "ix_position_lots_fifo",
            "wallet",
            "token_mint",
            "buy_timestamp",
        ),
        # Query open lots
        Index(
            "ix_position_lots_status",
            "wallet",
            "token_mint",
            "status",
        ),
        # Query by trade_id
        Index(
            "ix_position_lots_trade",
            "trade_id",
        ),
        {
            "comment": "FIFO buy lots for position cost basis tracking",
        },
    )

    def __repr__(self) -> str:
        return (
            f"<PositionLot {self.wallet[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"qty={self.remaining_quantity}/{self.original_quantity}>"
        )
