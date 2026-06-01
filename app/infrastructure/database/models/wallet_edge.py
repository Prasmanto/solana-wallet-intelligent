"""Wallet edge model — persistent storage for wallet graph edges.

Stores weighted edges between wallets with time-decay support.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletEdge(Base):
    """Wallet edge in the intelligence graph."""

    __tablename__ = "wallet_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_wallet: Mapped[str] = mapped_column(String(44), nullable=False)
    to_wallet: Mapped[str] = mapped_column(String(44), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    decay_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interaction_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_interaction: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_wallet_edges_from", "from_wallet"),
        Index("ix_wallet_edges_to", "to_wallet"),
        Index("ix_wallet_edges_pair", "from_wallet", "to_wallet", unique=True),
        Index("ix_wallet_edges_type", "edge_type"),
        {"comment": "Wallet edges in the intelligence graph"},
    )

    def __repr__(self) -> str:
        return f"<WalletEdge {self.from_wallet[:8]}... -> {self.to_wallet[:8]}... weight={self.weight}>"
