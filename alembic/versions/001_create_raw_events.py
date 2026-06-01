"""create_raw_events_table

Revision ID: 001_initial
Revises:
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create raw_events table
    op.create_table(
        "raw_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(36),
            unique=True,
            nullable=False,
            comment="Unique event identifier for idempotent inserts",
        ),
        sa.Column(
            "event_version",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
            comment="Schema version for forward compatibility",
        ),
        sa.Column(
            "stream_name",
            sa.String(128),
            nullable=False,
            comment="Redis Stream name",
        ),
        sa.Column(
            "event_type",
            sa.String(128),
            nullable=False,
            comment="Dot-separated event type",
        ),
        sa.Column(
            "correlation_id",
            sa.String(36),
            nullable=False,
            comment="Traces event through full pipeline",
        ),
        sa.Column(
            "causation_id",
            sa.String(36),
            nullable=False,
            server_default="",
            comment="ID of event that caused this one",
        ),
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            comment="Domain event data",
        ),
        sa.Column(
            "metadata",
            JSONB(),
            nullable=True,
            comment="Arbitrary metadata",
        ),
        sa.Column(
            "retry_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="Number of retry attempts",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="Event status",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="When event was first received",
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When event was fully processed",
        ),
        comment="Append-only raw event storage",
    )

    # Create indexes
    op.create_index(
        "ix_raw_events_event_id",
        "raw_events",
        ["event_id"],
        unique=True,
    )
    op.create_index(
        "ix_raw_events_stream_created",
        "raw_events",
        ["stream_name", "created_at"],
    )
    op.create_index(
        "ix_raw_events_correlation",
        "raw_events",
        ["correlation_id", "created_at"],
    )
    op.create_index(
        "ix_raw_events_type",
        "raw_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_raw_events_status",
        "raw_events",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_raw_events_causation",
        "raw_events",
        ["causation_id"],
    )
    op.create_index(
        "ix_raw_events_stream_status_time",
        "raw_events",
        ["stream_name", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("raw_events")
