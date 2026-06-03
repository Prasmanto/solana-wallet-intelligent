"""create_token_price_snapshots

Revision ID: 010_token_price_snapshots
Revises: 009_paper_trading
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "010_token_price_snapshots"
down_revision: Union[str, None] = "009_paper_trading"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_price_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_mint", sa.String(44), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("slot", sa.Integer(), nullable=True),
        sa.Column("context", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_token_price_snapshots_mint",
        "token_price_snapshots",
        ["token_mint"],
    )
    op.create_index(
        "ix_token_price_snapshots_fetched",
        "token_price_snapshots",
        ["fetched_at"],
    )
    op.create_index(
        "ix_token_price_snapshots_mint_fetched",
        "token_price_snapshots",
        ["token_mint", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_table("token_price_snapshots")
