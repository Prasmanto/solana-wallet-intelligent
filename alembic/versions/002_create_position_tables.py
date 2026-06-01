"""create_position_tables

Revision ID: 002_positions
Revises: 001_initial
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "002_positions"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create wallet_positions table
    op.create_table(
        "wallet_positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet", sa.String(44), nullable=False, comment="Wallet address"),
        sa.Column("token_mint", sa.String(44), nullable=False, comment="Token mint address"),
        sa.Column("position_size", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("avg_cost_basis", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_cost_basis", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("realized_roi", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("total_buys", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_sells", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_buy_volume", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_sell_volume", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_fees_paid", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("first_buy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_buy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_sell_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sell_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_duration_seconds", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_trade_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("metadata", JSONB(), nullable=True),
        comment="Wallet position state",
    )

    # Create indexes for wallet_positions
    op.create_index(
        "ix_wallet_positions_wallet_token",
        "wallet_positions",
        ["wallet", "token_mint"],
        unique=True,
    )
    op.create_index(
        "ix_wallet_positions_wallet",
        "wallet_positions",
        ["wallet"],
    )
    op.create_index(
        "ix_wallet_positions_token",
        "wallet_positions",
        ["token_mint"],
    )
    op.create_index(
        "ix_wallet_positions_last_trade",
        "wallet_positions",
        ["last_trade_at"],
    )

    # Create position_lots table
    op.create_table(
        "position_lots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet", sa.String(44), nullable=False),
        sa.Column("token_mint", sa.String(44), nullable=False),
        sa.Column("trade_id", sa.String(36), nullable=False),
        sa.Column("signature", sa.String(88), nullable=False),
        sa.Column("original_quantity", sa.Numeric(20, 9), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(20, 9), nullable=False),
        sa.Column("cost_basis_per_token", sa.Numeric(20, 9), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 9), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("buy_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        comment="FIFO buy lots",
    )

    # Create indexes for position_lots
    op.create_index(
        "ix_position_lots_fifo",
        "position_lots",
        ["wallet", "token_mint", "buy_timestamp"],
    )
    op.create_index(
        "ix_position_lots_status",
        "position_lots",
        ["wallet", "token_mint", "status"],
    )
    op.create_index(
        "ix_position_lots_trade",
        "position_lots",
        ["trade_id"],
    )


def downgrade() -> None:
    op.drop_table("position_lots")
    op.drop_table("wallet_positions")
