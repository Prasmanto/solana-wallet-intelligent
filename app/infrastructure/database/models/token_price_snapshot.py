"""Token price snapshot model — SQLAlchemy ORM for historical price data.

Captures point-in-time prices from Jupiter for:
- Paper trading entry/exit positions
- Top-ranked tokens per ranking window
- Entry timing analysis
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class TokenPriceSnapshot(Base):
    """Point-in-time token price snapshot."""

    __tablename__ = "token_price_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    token_mint: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
    )
    price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="jupiter, cache, fallback",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="1.0",
    )
    slot: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Solana slot number when price was observed",
    )
    context: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="scheduled",
        comment="paper_candidate, paper_position, ranked_token, scheduled",
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<TokenPriceSnapshot {str(self.id)[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"price={self.price} "
            f"context={self.context}>"
        )
