"""Raw event persistence service.

Orchestrates event persistence with:
- Idempotent inserts from Redis Streams
- Status lifecycle management
- Replay orchestration
- Batch operations for high throughput
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository

logger = structlog.get_logger(__name__)


class RawEventService:
    """Service for persisting and replaying raw events."""

    def __init__(self, repo: RawEventRepository) -> None:
        self._repo = repo

    # ── Persistence ─────────────────────────────────────────

    async def persist_envelope(
        self,
        envelope: EventEnvelope,
        stream_name: str,
        status: str = "pending",
    ) -> bool:
        """Persist an EventEnvelope to the raw_events table.

        Idempotent: returns False if event_id already exists.
        """
        return await self._repo.insert(
            event_id=envelope.event_id,
            stream_name=stream_name,
            event_type=envelope.event_type,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            payload=envelope.payload_dict,
            metadata=envelope.metadata_dict,
            retry_count=envelope.retry_count,
            status=status,
        )

    async def persist_from_redis(
        self,
        redis_id: str,
        stream_name: str,
        fields: dict[str, str],
    ) -> bool:
        """Persist a raw Redis Streams message to the database.

        Used by the ingestion worker to store events before processing.
        """
        try:
            envelope = EventEnvelope.from_dict(fields)
            return await self.persist_envelope(
                envelope=envelope,
                stream_name=stream_name,
                status="pending",
            )
        except Exception as e:
            logger.error(
                "raw_event.persist_failed",
                redis_id=redis_id,
                stream_name=stream_name,
                error=str(e),
            )
            return False

    async def persist_batch(
        self,
        envelopes: list[tuple[EventEnvelope, str]],
    ) -> int:
        """Persist multiple envelopes in a single round-trip.

        Args:
            envelopes: List of (EventEnvelope, stream_name) tuples.

        Returns:
            Number of events actually inserted (excluding duplicates).
        """
        events = []
        for envelope, stream_name in envelopes:
            events.append({
                "event_id": envelope.event_id,
                "stream_name": stream_name,
                "event_type": envelope.event_type,
                "correlation_id": envelope.correlation_id,
                "causation_id": envelope.causation_id,
                "payload": envelope.payload_dict,
                "metadata": envelope.metadata_dict,
                "retry_count": envelope.retry_count,
                "status": "pending",
            })

        return await self._repo.insert_batch(events)

    # ── Status Lifecycle ────────────────────────────────────

    async def mark_processing(self, event_id: str) -> bool:
        """Mark event as being processed."""
        return await self._repo.mark_processing(event_id)

    async def mark_completed(self, event_id: str) -> bool:
        """Mark event as fully processed."""
        return await self._repo.mark_completed(event_id)

    async def mark_failed(self, event_id: str) -> bool:
        """Mark event as failed."""
        return await self._repo.mark_failed(event_id)

    async def mark_dead_letter(self, event_id: str) -> bool:
        """Mark event as dead-lettered (max retries exceeded)."""
        return await self._repo.mark_dead_letter(event_id)

    # ── Replay ──────────────────────────────────────────────

    async def replay_stream(
        self,
        stream_name: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Replay events from a stream as dictionaries.

        Returns event data suitable for re-publishing to Redis Streams.
        """
        events = await self._repo.replay_by_stream(
            stream_name=stream_name,
            since=since,
            limit=limit,
        )
        return [self._to_replay_dict(e) for e in events]

    async def replay_correlation(
        self,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        """Replay the full pipeline trace for a correlation ID."""
        events = await self._repo.replay_by_correlation(correlation_id)
        return [self._to_replay_dict(e) for e in events]

    async def replay_failed(
        self,
        stream_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Replay failed events for reprocessing."""
        events = await self._repo.replay_failed(stream_name, limit)
        return [self._to_replay_dict(e) for e in events]

    # ── Analytics ───────────────────────────────────────────

    async def get_stream_stats(self) -> dict[str, Any]:
        """Get aggregate statistics for all streams."""
        counts_by_stream = await self._repo.count_by_stream()
        counts_by_status = await self._repo.count_by_status()

        return {
            "events_by_stream": counts_by_stream,
            "events_by_status": counts_by_status,
            "total_events": sum(counts_by_stream.values()),
        }

    async def get_stream_time_range(
        self,
        stream_name: str,
    ) -> dict[str, str | None]:
        """Get the time range of events in a stream."""
        earliest, latest = await self._repo.get_time_range(stream_name)
        return {
            "earliest": earliest.isoformat() if earliest else None,
            "latest": latest.isoformat() if latest else None,
        }

    # ── Helpers ─────────────────────────────────────────────

    def _to_replay_dict(self, event: Any) -> dict[str, Any]:
        """Convert a RawEvent model to a replay dictionary."""
        return {
            "event_id": event.event_id,
            "event_version": event.event_version,
            "stream_name": event.stream_name,
            "event_type": event.event_type,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "payload": event.payload,
            "metadata": event.metadata_,
            "retry_count": event.retry_count,
            "status": event.status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        }
