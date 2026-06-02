"""Paper trading models — SQLAlchemy ORM for paper trading tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class PaperPosition(Base):
    """Virtual paper trading position."""

    __tablename__ = "paper_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    token_mint: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
    )
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    ranking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    entry_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    entry_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    virtual_size_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="OPEN",
        comment="OPEN, CLOSED, SKIPPED",
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    exit_reason: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="STOP_LOSS, TAKE_PROFIT, TIMEOUT, MANUAL, SIGNAL_DECAY",
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaperPosition {str(self.id)[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"status={self.status}>"
        )


class PaperTradeOutcome(Base):
    """Outcome of a closed paper trade."""

    __tablename__ = "paper_trade_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    token_mint: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
    )
    entry_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    exit_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    roi: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Return on investment as percentage",
    )
    pnl_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Profit/loss in USD",
    )
    max_drawdown: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    max_return: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    holding_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    outcome_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="OPEN",
        comment="WIN, LOSS, BREAKEVEN, TIMEOUT",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaperTradeOutcome {str(self.id)[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"roi={self.roi}>"
        )


class PaperPortfolioSnapshot(Base):
    """Periodic snapshot of paper trading portfolio state."""

    __tablename__ = "paper_portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    portfolio_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    cash_balance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    open_positions_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    unrealized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    realized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaperPortfolioSnapshot {str(self.id)[:8]}... "
            f"value={self.portfolio_value}>"
        )
