"""Wallet metrics model — aggregated wallet intelligence metrics.

Stores computed metrics for each wallet, updated by the aggregation worker.
Metrics are deterministic and replay-safe (versioned).
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletMetrics(Base):
    """Aggregated metrics for a wallet.

    Updated atomically by the aggregation worker.
    Versioned for replay safety.
    """

    __tablename__ = "wallet_metrics"

    # ── Primary Key ─────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── Identity ────────────────────────────────────────────
    wallet: Mapped[str] = mapped_column(
        String(44),
        unique=True,
        nullable=False,
        comment="Wallet address",
    )

    # ── PnL Metrics ─────────────────────────────────────────
    total_realized_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    total_realized_roi: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        default=0,
    )
    total_fees_paid: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    net_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )

    # ── Win/Loss Metrics ────────────────────────────────────
    total_wins: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    total_losses: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    win_rate: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        default=0,
    )
    avg_win_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    avg_loss_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    best_trade_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    worst_trade_pnl: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    best_trade_token: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
        default="",
    )
    worst_trade_token: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
        default="",
    )

    # ── Position Metrics ────────────────────────────────────
    total_unique_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    active_positions: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    total_trades: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    total_buys: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    total_sells: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    # ── Volume Metrics ──────────────────────────────────────
    total_buy_volume: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    total_sell_volume: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    total_volume: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )

    # ── Hold Duration ───────────────────────────────────────
    avg_hold_duration_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    # ── Position Size ───────────────────────────────────────
    avg_position_size: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )
    max_position_size: Mapped[float] = mapped_column(
        Numeric(20, 9),
        nullable=False,
        default=0,
    )

    # ── Timestamps ──────────────────────────────────────────
    first_trade_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_trade_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # ── Versioning (replay safety) ──────────────────────────
    metrics_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
    )
    last_trade_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        default="",
    )

    # ── Metadata ────────────────────────────────────────────
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    # ── Indexes ─────────────────────────────────────────────
    __table_args__ = (
        Index("ix_wallet_metrics_wallet", "wallet", unique=True),
        Index("ix_wallet_metrics_pnl", "total_realized_pnl"),
        Index("ix_wallet_metrics_last_trade", "last_trade_at"),
        {
            "comment": "Aggregated wallet intelligence metrics",
        },
    )

    def __repr__(self) -> str:
        return (
            f"<WalletMetrics {self.wallet[:8]}... "
            f"pnl={self.total_realized_pnl} "
            f"trades={self.total_trades}>"
        )
