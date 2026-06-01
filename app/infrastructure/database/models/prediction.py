"""Prediction model — SQLAlchemy ORM for predictions table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class Prediction(Base):
    """Prediction record."""

    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    prediction_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
    )
    cluster_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="",
    )
    predicted_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    predicted_probability: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    predicted_eta_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="60",
    )
    prediction_horizon: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default="1h",
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="PENDING",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction {str(self.id)[:8]}... "
            f"token={self.token[:8]}... "
            f"score={self.predicted_score}>"
        )
