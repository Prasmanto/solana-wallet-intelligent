"""Wallet feature model — persistent storage for wallet features.

Stores computed features per time window (5m, 1h, 24h).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletFeature(Base):
    """Wallet features per time window."""

    __tablename__ = "wallet_features"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False)
    time_window: Mapped[str] = mapped_column(String(10), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tx_frequency: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_interval: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    token_diversity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    buy_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sell_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transfer_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    buy_sell_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interaction_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    features_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_wallet_features_wallet", "wallet_address"),
        Index("ix_wallet_features_window", "wallet_address", "time_window"),
        Index("ix_wallet_features_time", "computed_at"),
        {"comment": "Wallet features per time window"},
    )

    def __repr__(self) -> str:
        return f"<WalletFeature {self.wallet_address[:8]}... window={self.time_window}>"
