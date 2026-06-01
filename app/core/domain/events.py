"""Event envelope schema.

Every event flowing through Redis Streams is wrapped in an envelope
that carries metadata for tracing, retry, and ordering.

Envelope structure (Redis Streams field map):
    event_id        — UUID v7 (time-ordered, unique)
    event_type      — e.g. "raw.received", "trade.normalized"
    correlation_id  — traces a transaction through the full pipeline
    causation_id    — ID of the event that caused this one (chain linking)
    timestamp       — ISO 8601 creation time
    retry_count     — how many times this event has been retried
    max_retries     — retry ceiling before dead-letter
    payload         — JSON-serialized domain event data
    metadata        — JSON-serialized arbitrary key-value pairs
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    """Immutable event envelope for Redis Streams.

    Instances are created via `EventEnvelope.create()` or
    `EventEnvelope.from_dict()` (deserialization).
    """

    event_id: str
    event_type: str
    correlation_id: str
    causation_id: str
    timestamp: str
    retry_count: int
    max_retries: int
    payload: str  # JSON string
    metadata: str  # JSON string

    # ── Factory ─────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        causation_id: str | None = None,
        max_retries: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        """Create a new event envelope.

        Args:
            event_type: Dot-separated event type (e.g. "raw.received").
            payload: Domain event data (will be JSON-serialized).
            correlation_id: Traces the event through the pipeline. Auto-generated if None.
            causation_id: ID of the event that triggered this one.
            max_retries: Max retry attempts before dead-lettering.
            metadata: Arbitrary metadata (request_id, source, etc.).
        """
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            correlation_id=correlation_id or str(uuid.uuid4()),
            causation_id=causation_id or "",
            timestamp=now,
            retry_count=0,
            max_retries=max_retries,
            payload=json.dumps(payload, default=str),
            metadata=json.dumps(metadata or {}, default=str),
        )

    # ── Serialization ───────────────────────────────────────

    def to_dict(self) -> dict[str, str]:
        """Serialize to Redis Streams field map (all values must be strings)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp,
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "payload": self.payload,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> EventEnvelope:
        """Deserialize from Redis Streams field map."""
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            correlation_id=data["correlation_id"],
            causation_id=data.get("causation_id", ""),
            timestamp=data["timestamp"],
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            payload=data.get("payload", "{}"),
            metadata=data.get("metadata", "{}"),
        )

    # ── Helpers ─────────────────────────────────────────────

    @property
    def payload_dict(self) -> dict[str, Any]:
        """Deserialize payload JSON."""
        return json.loads(self.payload)

    @property
    def metadata_dict(self) -> dict[str, Any]:
        """Deserialize metadata JSON."""
        return json.loads(self.metadata)

    @property
    def is_retryable(self) -> bool:
        """Check if this event can be retried."""
        return self.retry_count < self.max_retries

    def increment_retry(self) -> EventEnvelope:
        """Return a new envelope with retry_count incremented."""
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            timestamp=self.timestamp,
            retry_count=self.retry_count + 1,
            max_retries=self.max_retries,
            payload=self.payload,
            metadata=self.metadata,
        )

    def with_causation(self, causation_id: str) -> EventEnvelope:
        """Return a new envelope with causation_id set (for chain linking)."""
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type,
            correlation_id=self.correlation_id,
            causation_id=causation_id,
            timestamp=self.timestamp,
            retry_count=self.retry_count,
            max_retries=self.max_retries,
            payload=self.payload,
            metadata=self.metadata,
        )
