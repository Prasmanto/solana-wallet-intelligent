"""Token ranking model — SQLAlchemy ORM for token_rankings table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class TokenRanking(Base):
    """Token ranking record produced by RankingWorker."""

    __tablename__ = "token_rankings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    token_mint: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
    )
    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    regime: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="NORMAL",
    )
    stage: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="EARLY_STAGE",
    )
    alpha_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    is_leader: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0",
    )
    signals_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    ranking_window: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="",
        comment="Ranking window identifier (ISO timestamp of window start)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<TokenRanking {str(self.id)[:8]}... "
            f"token={self.token_mint[:8]}... "
            f"score={self.score} rank={self.rank}>"
        )
