from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Transaction(Base):
    """Parsed Solana transaction record."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False
    )
    signature: Mapped[str] = mapped_column(String(88), unique=True, nullable=False)
    slot: Mapped[int] = mapped_column(nullable=False)
    block_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tx_type: Mapped[str] = mapped_column(String(50), nullable=False)
    program_id: Mapped[str | None] = mapped_column(String(44), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 9), nullable=True)
    mint: Mapped[str | None] = mapped_column(String(44), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    wallet = relationship("Wallet", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_signature", "signature"),
        Index("ix_transactions_wallet_slot", "wallet_id", "slot"),
        Index("ix_transactions_block_time", "block_time"),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.signature[:16]}...>"
