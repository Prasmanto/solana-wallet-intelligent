"""Position state model — SQLAlchemy async ORM for wallet positions.

Tracks per-wallet, per-token position state with:
- Current position size
- Average cost basis
- Realized PnL
- Trade statistics
- Hold duration

Design:
- Append-only updates (state is reconstructed from events)
- Idempotent (trade_id is unique constraint)
- Indexed for wallet + token queries
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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletPosition(Base):
    """Current position state for a wallet + token pair.

    This is the canonical source of truth for position state.
    Updated atomically by the position worker.
    """

    __tablename__ = "wallet_positions"

    # ── Primary Key ─────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── Identity (wallet + token pair) ──────────────────────
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

    # ── Position State ──────────────────────────────────────
    position_size: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Current position size (human-readable)",
    )
    avg_cost_basis: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Average cost basis per token",
    )
    total_cost_basis: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Total cost basis (position_size * avg_cost_basis)",
    )

    # ── Realized PnL ────────────────────────────────────────
    realized_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Total realized PnL",
    )
    realized_roi: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        default=0,
        comment="Realized ROI as percentage",
    )

    # ── Trade Statistics ─────────────────────────────────────
    total_buys: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Total number of buy trades",
    )
    total_sells: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Total number of sell trades",
    )
    total_buy_volume: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Total volume bought (in token)",
    )
    total_sell_volume: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Total volume sold (in token)",
    )
    total_fees_paid: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
        comment="Total fees paid (in SOL)",
    )

    # ── Timestamps ──────────────────────────────────────────
    first_buy_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of first buy",
    )
    last_buy_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last buy",
    )
    first_sell_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of first sell",
    )
    last_sell_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last sell",
    )
    last_trade_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last trade (buy or sell)",
    )

    # ── Hold Duration ───────────────────────────────────────
    hold_duration_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Total hold duration in seconds",
    )

    # ── Event Tracking (replay safety) ──────────────────────
    last_trade_id: Mapped[str] = mapped_column(
        String(88),
        nullable=False,
        default="",
        comment="ID of last processed trade (for idempotency)",
    )
    last_processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this position was last updated",
    )
    event_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        comment="Event version for optimistic locking",
    )

    # ── Metadata ────────────────────────────────────────────
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional position metadata",
    )

    # ── Indexes ─────────────────────────────────────────────
    __table_args__ = (
        # Unique constraint: one position per wallet + token
        Index(
            "ix_wallet_positions_wallet_token",
            "wallet",
            "token_mint",
            unique=True,
        ),
        # Query by wallet
        Index(
            "ix_wallet_positions_wallet",
            "wallet",
        ),
        # Query by token
        Index(
            "ix_wallet_positions_token",
            "token_mint",
        ),
        # Query by last trade time
        Index(
            "ix_wallet_positions_last_trade",
            "last_trade_at",
        ),
        {
            "comment": "Wallet position state (per wallet + token pair)",
        },
    )

    def __repr__(self) -> str:
        return (
            f"<WalletPosition {self.wallet[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"size={self.position_size}>"
        )
