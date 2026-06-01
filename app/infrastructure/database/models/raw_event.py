"""Raw event model — append-only storage for immutable event history.

Production-grade design:
- Append-only: events are never updated, only inserted
- Idempotent: event_id = hash(signature + slot + type) with UNIQUE constraint
- Indexed for replay: by stream, correlation_id, event_type, created_at
- High write throughput: minimal indexes, TOAST for large payloads
- DLQ tracking: retry_count and status for failure handling
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.session import Base


class RawEvent(Base):
    """Append-only raw event storage.

    Production guarantees:
    - event_id is UNIQUE (ON CONFLICT DO NOTHING for idempotency)
    - Status tracks lifecycle: pending → processing → completed/failed/dead_letter
    - retry_count tracks retry attempts
    - processed_at records when event was fully processed
    """

    __tablename__ = "raw_events"

    # ── Primary Key ─────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── Event Identity (unique, idempotent insert key) ──────
    event_id: Mapped[str] = mapped_column(
        String(64),  # Hash-based ID (SHA256 hex = 64 chars)
        unique=True,
        nullable=False,
        index=True,
        comment="Deterministic event ID: SHA256(signature + slot + type)",
    )

    # ── Event Routing ───────────────────────────────────────
    event_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        comment="Schema version for forward compatibility",
    )
    stream_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Redis Stream name (e.g. solana_intel.raw.pending)",
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Dot-separated event type (e.g. raw.received)",
    )

    # ── Correlation / Causation (replay chain tracing) ──────
    correlation_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        comment="Traces event through full pipeline",
    )
    causation_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        server_default="",
        comment="ID of event that caused this one (chain linking)",
    )

    # ── Payload (JSONB for flexible querying) ───────────────
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Domain event data (JSON)",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Arbitrary metadata (request_id, source, etc.)",
    )

    # ── Status Tracking ─────────────────────────────────────
    retry_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Number of times this event has been retried",
    )
    max_retries: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=5,
        comment="Maximum retry attempts before dead-lettering",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="Event status: pending | processing | completed | failed | dead_letter",
    )

    # ── Timestamps ──────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When the event was first received",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the event was fully processed",
    )
    last_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the event was last retried",
    )

    # ── Error Tracking ──────────────────────────────────────
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message (for debugging)",
    )

    # ── Indexes (optimized for replay queries) ──────────────
    __table_args__ = (
        # 1. Replay by stream + time (most common)
        Index(
            "ix_raw_events_stream_created",
            "stream_name",
            "created_at",
        ),

        # 2. Trace a correlation through the pipeline
        Index(
            "ix_raw_events_correlation",
            "correlation_id",
            "created_at",
        ),

        # 3. Filter by event type
        Index(
            "ix_raw_events_type",
            "event_type",
            "created_at",
        ),

        # 4. Replay by status (pending events for reprocessing)
        Index(
            "ix_raw_events_status",
            "status",
            "created_at",
        ),

        # 5. Chain linking (causation_id lookups)
        Index(
            "ix_raw_events_causation",
            "causation_id",
        ),

        # 6. Composite: stream + status + time (replay failed events)
        Index(
            "ix_raw_events_stream_status_time",
            "stream_name",
            "status",
            "created_at",
        ),

        # 7. DLQ lookup (find dead-lettered events)
        Index(
            "ix_raw_events_dlq",
            "status",
            "retry_count",
            "created_at",
        ),

        {
            "comment": "Append-only raw event storage for immutable event history",
        },
    )

    def __repr__(self) -> str:
        return (
            f"<RawEvent {self.event_id[:12]}... "
            f"type={self.event_type} status={self.status}>"
        )
