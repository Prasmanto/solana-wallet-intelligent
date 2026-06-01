"""create_calibration_monitoring_tables

Revision ID: 006_calibration_monitoring
Revises: 005_evaluation
Create Date: 2026-05-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "006_calibration_monitoring"
down_revision: Union[str, None] = "005_evaluation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # calibration_snapshots table
    op.create_table(
        "calibration_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("signal_weights_json", JSONB(), nullable=False),
        sa.Column("confidence_scaling_json", JSONB(), nullable=False),
        sa.Column("regime_adjustments_json", JSONB(), nullable=False),
        sa.Column("engine_adjustments_json", JSONB(), nullable=False),
    )
    op.create_index("ix_snapshots_created", "calibration_snapshots", ["created_at"])

    # calibration_stability table
    op.create_table(
        "calibration_stability",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False),
        sa.Column("readiness_score", sa.Float(), nullable=False),
        sa.Column("weight_stability", sa.Float(), nullable=False),
        sa.Column("convergence_score", sa.Float(), nullable=False),
        sa.Column("volatility_score", sa.Float(), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_stability_snapshot", "calibration_stability", ["snapshot_id"])

    # calibration_drift table
    op.create_table(
        "calibration_drift",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_name", sa.String(50), nullable=False),
        sa.Column("previous_value", sa.Float(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("daily_change", sa.Float(), nullable=False),
        sa.Column("weekly_change", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_drift_signal", "calibration_drift", ["signal_name"])
    op.create_index("ix_drift_created", "calibration_drift", ["created_at"])


def downgrade() -> None:
    op.drop_table("calibration_drift")
    op.drop_table("calibration_stability")
    op.drop_table("calibration_snapshots")
