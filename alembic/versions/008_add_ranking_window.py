"""add_ranking_window_column

Revision ID: 008_add_ranking_window
Revises: 007_token_rankings
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_add_ranking_window"
down_revision: Union[str, None] = "007_token_rankings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "token_rankings",
        sa.Column(
            "ranking_window",
            sa.String(30),
            nullable=False,
            server_default="",
            comment="Ranking window identifier",
        ),
    )
    op.create_index(
        "ix_token_rankings_window",
        "token_rankings",
        ["ranking_window"],
    )


def downgrade() -> None:
    op.drop_index("ix_token_rankings_window", "token_rankings")
    op.drop_column("token_rankings", "ranking_window")
