"""Redis Streams consumer — handles XREADGROUP and XAUTOCLAIM.

Production-grade consumer with:
- XREADGROUP for new messages
- XAUTOCLAIM for crash recovery
- Structured logging
"""

from __future__ import annotations

from typing import Any

import structlog

from app.infrastructure.redis.streams import StreamsManager

logger = structlog.get_logger(__name__)


class StreamConsumer:
    """Handles Redis Streams consumer operations."""

    def __init__(self, streams: StreamsManager) -> None:
        self._streams = streams

    async def read_new(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, str]]]:
        """Read new messages from consumer group.

        Returns list of (redis_id, fields) tuples.
        """
        return await self._streams.read_group(
            stream=stream,
            group=group,
            consumer=consumer,
            count=count,
            block_ms=block_ms,
        )

    async def reclaim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        min_idle_ms: int = 60_000,
    ) -> list[tuple[str, dict[str, str]]]:
        """Reclaim pending messages from crashed consumers.

        Uses XAUTOCLAIM to find messages idle for > min_idle_ms.
        """
        return await self._streams.read_group_pending(
            stream=stream,
            group=group,
            consumer=consumer,
            count=count,
            min_idle_ms=min_idle_ms,
        )

    async def ack(
        self,
        stream: str,
        group: str,
        *redis_ids: str,
    ) -> int:
        """Acknowledge processed messages."""
        return await self._streams.ack(stream, group, *redis_ids)

    async def send_to_dlq(
        self,
        original_stream: str,
        redis_id: str,
        fields: dict[str, str],
        reason: str,
    ) -> str:
        """Move message to dead-letter queue."""
        return await self._streams.send_to_dlq(
            original_stream=original_stream,
            redis_id=redis_id,
            fields=fields,
            reason=reason,
        )
