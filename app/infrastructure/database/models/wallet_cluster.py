"""Wallet cluster model — persistent storage for wallet clusters.

Stores cluster membership and versioning for stability across restarts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class WalletCluster(Base):
    """Wallet cluster membership."""

    __tablename__ = "wallet_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cluster_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_wallet_clusters_wallet", "wallet_address"),
        Index("ix_wallet_clusters_version", "cluster_id", "cluster_version"),
        {"comment": "Wallet cluster membership"},
    )

    def __repr__(self) -> str:
        return f"<WalletCluster {self.wallet_address[:8]}... cluster={self.cluster_id[:8]}>"


class ClusterHistory(Base):
    """Cluster history for tracking merges and splits."""

    __tablename__ = "wallet_cluster_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    old_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    new_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_shift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_cluster_history_cluster", "cluster_id"),
        Index("ix_cluster_history_wallet", "wallet_address"),
        Index("ix_cluster_history_time", "created_at"),
        {"comment": "Cluster history for tracking merges and splits"},
    )

    def __repr__(self) -> str:
        return f"<ClusterHistory {self.wallet_address[:8]}... {self.event_type}>"
