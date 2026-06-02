"""create_paper_trading_tables

Revision ID: 009_paper_trading
Revises: 008_add_ranking_window
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "009_paper_trading"
down_revision: Union[str, None] = "008_add_ranking_window"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # paper_positions
    op.create_table(
        "paper_positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_mint", sa.String(44), nullable=False),
        sa.Column("prediction_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ranking_id", UUID(as_uuid=True), nullable=True),
        sa.Column("entry_score", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("virtual_size_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_paper_positions_token", "paper_positions", ["token_mint"])
    op.create_index("ix_paper_positions_status", "paper_positions", ["status"])
    op.create_index("ix_paper_positions_opened", "paper_positions", ["opened_at"])

    # paper_trade_outcomes
    op.create_table(
        "paper_trade_outcomes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("position_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token_mint", sa.String(44), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("max_return", sa.Float(), nullable=True),
        sa.Column("holding_seconds", sa.Integer(), nullable=True),
        sa.Column("outcome_status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_paper_outcomes_position", "paper_trade_outcomes", ["position_id"])
    op.create_index("ix_paper_outcomes_token", "paper_trade_outcomes", ["token_mint"])

    # paper_portfolio_snapshots
    op.create_table(
        "paper_portfolio_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cash_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("open_positions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_paper_snapshots_created", "paper_portfolio_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_table("paper_portfolio_snapshots")
    op.drop_table("paper_trade_outcomes")
    op.drop_table("paper_positions")
