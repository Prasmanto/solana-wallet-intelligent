"""create_evaluation_tables

Revision ID: 005_evaluation
Revises: 004_wallet_intelligence
Create Date: 2026-05-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "005_evaluation"
down_revision: Union[str, None] = "004_wallet_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # predictions table
    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prediction_type", sa.String(50), nullable=False),
        sa.Column("token", sa.String(44), nullable=False),
        sa.Column("cluster_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("predicted_score", sa.Float(), nullable=False),
        sa.Column("predicted_probability", sa.Float(), nullable=False),
        sa.Column("predicted_eta_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("prediction_horizon", sa.String(10), nullable=False, server_default="1h"),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
    )
    op.create_index("ix_predictions_type", "predictions", ["prediction_type"])
    op.create_index("ix_predictions_token", "predictions", ["token"])
    op.create_index("ix_predictions_status", "predictions", ["status"])
    op.create_index("ix_predictions_horizon", "predictions", ["prediction_horizon"])
    op.create_index("ix_predictions_created", "predictions", ["created_at"])

    # prediction_outcomes table
    op.create_table(
        "prediction_outcomes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prediction_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actual_return_15m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_return_1h", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_return_4h", sa.Float(), nullable=False, server_default="0"),
        sa.Column("volume_change", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("outcome_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("resolution_reason", sa.String(100), nullable=False, server_default=""),
    )
    op.create_index("ix_outcomes_prediction", "prediction_outcomes", ["prediction_id"])
    op.create_index("ix_outcomes_resolved", "prediction_outcomes", ["resolved_at"])

    # prediction_metrics table
    op.create_table(
        "prediction_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_metrics_name", "prediction_metrics", ["metric_name"], unique=True)


def downgrade() -> None:
    op.drop_table("prediction_metrics")
    op.drop_table("prediction_outcomes")
    op.drop_table("predictions")
