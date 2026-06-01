"""Raw event repository — async CRUD and replay queries.

Design:
- Idempotent inserts (ON CONFLICT DO NOTHING)
- Append-only (no update/delete methods)
- Optimized for replay queries (time-range, correlation, status)
- High write throughput (batch inserts)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import Select, and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.raw_event import RawEvent

logger = structlog.get_logger(__name__)


class RawEventRepository:
    """Async repository for raw event persistence and replay."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write (Idempotent) ──────────────────────────────────

    async def insert(
        self,
        *,
        event_id: str,
        event_version: int = 1,
        stream_name: str,
        event_type: str,
        correlation_id: str,
        causation_id: str = "",
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        retry_count: int = 0,
        status: str = "pending",
    ) -> bool:
        """Insert a raw event. Returns True if inserted, False if duplicate.

        Uses PostgreSQL ON CONFLICT DO NOTHING for idempotent inserts.
        This ensures replay-safe event persistence.
        """
        now = datetime.now(timezone.utc)

        stmt = (
            pg_insert(RawEvent)
            .values(
                id=uuid.uuid4(),
                event_id=event_id,
                event_version=event_version,
                stream_name=stream_name,
                event_type=event_type,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload=payload,
                metadata_=metadata,
                retry_count=retry_count,
                status=status,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

        result = await self._session.execute(stmt)
        inserted = result.rowcount > 0

        if inserted:
            logger.debug("raw_event.inserted", event_id=event_id[:16])
        else:
            logger.debug("raw_event.duplicate", event_id=event_id[:16])

        return inserted

    async def insert_batch(
        self,
        events: list[dict[str, Any]],
    ) -> int:
        """Insert multiple raw events in a single round-trip.

        Returns the number of events actually inserted (excluding duplicates).
        """
        if not events:
            return 0

        now = datetime.now(timezone.utc)

        rows = []
        for event in events:
            rows.append({
                "id": uuid.uuid4(),
                "event_id": event["event_id"],
                "event_version": event.get("event_version", 1),
                "stream_name": event["stream_name"],
                "event_type": event["event_type"],
                "correlation_id": event["correlation_id"],
                "causation_id": event.get("causation_id", ""),
                "payload": event["payload"],
                "metadata_": event.get("metadata"),
                "retry_count": event.get("retry_count", 0),
                "status": event.get("status", "pending"),
                "created_at": now,
            })

        stmt = (
            pg_insert(RawEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

        result = await self._session.execute(stmt)
        inserted = result.rowcount

        logger.info("raw_event.batch_inserted", count=inserted, total=len(rows))
        return inserted

    # ── Status Updates (append-only, status is the only mutable field) ──

    async def mark_processing(self, event_id: str) -> bool:
        """Mark event as processing. Returns True if updated."""
        stmt = (
            RawEvent.__table__.update()
            .where(RawEvent.event_id == event_id)
            .values(status="processing")
        )
        result = await self._session.execute(stmt)
        # Invalidate identity map for this object
        self._session.expire_all()
        return result.rowcount > 0

    async def mark_completed(self, event_id: str) -> bool:
        """Mark event as completed with processed_at timestamp."""
        now = datetime.now(timezone.utc)
        stmt = (
            RawEvent.__table__.update()
            .where(RawEvent.event_id == event_id)
            .values(status="completed", processed_at=now)
        )
        result = await self._session.execute(stmt)
        # Invalidate identity map for this object
        self._session.expire_all()
        return result.rowcount > 0

    async def mark_failed(self, event_id: str) -> bool:
        """Mark event as failed."""
        stmt = (
            RawEvent.__table__.update()
            .where(RawEvent.event_id == event_id)
            .values(status="failed")
        )
        result = await self._session.execute(stmt)
        # Invalidate identity map for this object
        self._session.expire_all()
        return result.rowcount > 0

    async def mark_dead_letter(self, event_id: str) -> bool:
        """Mark event as dead-lettered."""
        stmt = (
            RawEvent.__table__.update()
            .where(RawEvent.event_id == event_id)
            .values(status="dead_letter")
        )
        result = await self._session.execute(stmt)
        # Invalidate identity map for this object
        self._session.expire_all()
        return result.rowcount > 0

    # ── Read (Single) ───────────────────────────────────────

    async def get_by_event_id(self, event_id: str) -> RawEvent | None:
        """Get a raw event by its unique event_id."""
        stmt = select(RawEvent).where(RawEvent.event_id == event_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, id: uuid.UUID) -> RawEvent | None:
        """Get a raw event by primary key."""
        stmt = select(RawEvent).where(RawEvent.id == id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (Replay Queries) ───────────────────────────────

    async def replay_by_stream(
        self,
        stream_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RawEvent]:
        """Replay events from a specific stream within a time range.

        Primary replay pattern: reprocess all events from a stream
        starting from a given timestamp.
        """
        stmt: Select = (
            select(RawEvent)
            .where(RawEvent.stream_name == stream_name)
            .order_by(RawEvent.created_at.asc())
        )

        if since:
            stmt = stmt.where(RawEvent.created_at >= since)
        if until:
            stmt = stmt.where(RawEvent.created_at <= until)

        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replay_by_correlation(
        self,
        correlation_id: str,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Replay all events in a correlation chain.

        Traces a single transaction through the entire pipeline.
        Returns events ordered by creation time.
        """
        stmt = (
            select(RawEvent)
            .where(RawEvent.correlation_id == correlation_id)
            .order_by(RawEvent.created_at.asc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replay_by_status(
        self,
        status: str,
        stream_name: str | None = None,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Replay events by status (e.g., 'failed', 'pending').

        Useful for reprocessing failed events or catching up on pending work.
        """
        conditions = [RawEvent.status == status]

        if stream_name:
            conditions.append(RawEvent.stream_name == stream_name)

        stmt = (
            select(RawEvent)
            .where(and_(*conditions))
            .order_by(RawEvent.created_at.asc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replay_by_type(
        self,
        event_type: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Replay events by type (e.g., 'raw.received', 'trade.normalized').

        Useful for analytics or type-specific reprocessing.
        """
        conditions = [RawEvent.event_type == event_type]

        if since:
            conditions.append(RawEvent.created_at >= since)

        stmt = (
            select(RawEvent)
            .where(and_(*conditions))
            .order_by(RawEvent.created_at.asc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replay_failed(
        self,
        stream_name: str | None = None,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Replay all failed events for reprocessing."""
        return await self.replay_by_status("failed", stream_name, limit)

    async def replay_chain(
        self,
        causation_id: str,
        limit: int = 100,
    ) -> list[RawEvent]:
        """Replay a causal chain starting from a specific event.

        Follows causation_id links to reconstruct the event lineage.
        """
        stmt = (
            select(RawEvent)
            .where(RawEvent.causation_id == causation_id)
            .order_by(RawEvent.created_at.asc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Analytics Queries ───────────────────────────────────

    async def count_by_stream(
        self,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Count events per stream."""
        stmt = (
            select(
                RawEvent.stream_name,
                func.count(RawEvent.id).label("count"),
            )
            .group_by(RawEvent.stream_name)
        )

        if since:
            stmt = stmt.where(RawEvent.created_at >= since)

        result = await self._session.execute(stmt)
        return {row.stream_name: row.count for row in result}

    async def count_by_status(
        self,
        stream_name: str | None = None,
    ) -> dict[str, int]:
        """Count events per status."""
        conditions = []
        if stream_name:
            conditions.append(RawEvent.stream_name == stream_name)

        stmt = (
            select(
                RawEvent.status,
                func.count(RawEvent.id).label("count"),
            )
            .group_by(RawEvent.status)
        )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self._session.execute(stmt)
        return {row.status: row.count for row in result}

    async def get_time_range(
        self,
        stream_name: str,
    ) -> tuple[datetime | None, datetime | None]:
        """Get the earliest and latest event times for a stream."""
        stmt = select(
            func.min(RawEvent.created_at).label("earliest"),
            func.max(RawEvent.created_at).label("latest"),
        ).where(RawEvent.stream_name == stream_name)

        result = await self._session.execute(stmt)
        row = result.one_or_none()
        if row:
            return row.earliest, row.latest
        return None, None
