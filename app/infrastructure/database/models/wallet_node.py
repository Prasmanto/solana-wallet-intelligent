"""Wallet node model — persistent storage for wallet graph nodes.

Stores wallet metadata and interaction counts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletNode(Base):
    """Wallet node in the intelligence graph."""

    __tablename__ = "wallet_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(
        String(44), unique=True, nullable=False, index=True
    )
    interaction_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cluster_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    wallet_type: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_wallet_nodes_cluster", "cluster_id"),
        Index("ix_wallet_nodes_type", "wallet_type"),
        {"comment": "Wallet nodes in the intelligence graph"},
    )

    def __repr__(self) -> str:
        return f"<WalletNode {self.wallet_address[:8]}... cluster={self.cluster_id[:8]}>"
