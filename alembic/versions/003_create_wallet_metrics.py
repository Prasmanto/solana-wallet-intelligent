"""create_wallet_metrics_table

Revision ID: 003_wallet_metrics
Revises: 002_positions
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "003_wallet_metrics"
down_revision: Union[str, None] = "002_positions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create wallet_metrics table
    op.create_table(
        "wallet_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet", sa.String(44), unique=True, nullable=False),
        sa.Column("total_realized_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_realized_roi", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("total_fees_paid", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_wins", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_losses", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("avg_win_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("avg_loss_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("best_trade_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("worst_trade_pnl", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("best_trade_token", sa.String(44), nullable=False, server_default=""),
        sa.Column("worst_trade_token", sa.String(44), nullable=False, server_default=""),
        sa.Column("total_unique_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_positions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_trades", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_buys", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_sells", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_buy_volume", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_sell_volume", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("total_volume", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("avg_hold_duration_seconds", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_position_size", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("max_position_size", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("first_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metrics_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("last_trade_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("metadata", JSONB(), nullable=True),
        comment="Aggregated wallet intelligence metrics",
    )

    # Create indexes
    op.create_index("ix_wallet_metrics_wallet", "wallet_metrics", ["wallet"], unique=True)
    op.create_index("ix_wallet_metrics_pnl", "wallet_metrics", ["total_realized_pnl"])
    op.create_index("ix_wallet_metrics_last_trade", "wallet_metrics", ["last_trade_at"])


def downgrade() -> None:
    op.drop_table("wallet_metrics")
