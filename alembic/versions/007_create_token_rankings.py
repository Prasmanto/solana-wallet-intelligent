"""create_token_rankings

Revision ID: 007_token_rankings
Revises: 006_calibration_monitoring
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "007_token_rankings"
down_revision: Union[str, None] = "006_calibration_monitoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_rankings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_mint", sa.String(44), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prediction_id", UUID(as_uuid=True), nullable=True),
        sa.Column("regime", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("stage", sa.String(30), nullable=False, server_default="EARLY_STAGE"),
        sa.Column("alpha_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_leader", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("signals_json", JSONB(), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_token_rankings_token", "token_rankings", ["token_mint"])
    op.create_index("ix_token_rankings_score", "token_rankings", ["score"])
    op.create_index("ix_token_rankings_created", "token_rankings", ["created_at"])
    op.create_index(
        "ix_token_rankings_token_prediction",
        "token_rankings",
        ["token_mint", "prediction_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("token_rankings")
