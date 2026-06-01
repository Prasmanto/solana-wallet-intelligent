"""Redis Streams manager.

Manages consumer groups, provides read/write primitives, and handles
stream lifecycle (group creation, trimming, pending message inspection).

This is the low-level Streams interface. Higher-level abstractions
(Producer, ConsumerWorker) build on top of it.
"""

from __future__ import annotations

from typing import Any

import structlog
from redis.asyncio import Redis

from app.core.domain.stream_names import StreamName

logger = structlog.get_logger(__name__)


class StreamsManager:
    """Low-level Redis Streams operations."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ── Consumer Groups ─────────────────────────────────────

    async def ensure_groups(self) -> None:
        """Create consumer groups for all known streams (idempotent)."""
        logger.info("streams.ensure_groups_starting", stream_count=len(StreamName.GROUPS))
        
        for stream, definitions in StreamName.GROUPS.items():
            for group_name, _consumer in definitions:
                try:
                    await self._redis.xgroup_create(
                        stream,
                        group_name,
                        id="0",
                        mkstream=True,
                    )
                    logger.info(
                        "streams.group_created",
                        stream=stream,
                        group=group_name,
                    )
                except Exception as e:
                    # BUSYGROUP means group already exists — safe to ignore
                    if "BUSYGROUP" in str(e):
                        logger.debug(
                            "streams.group_exists",
                            stream=stream,
                            group=group_name,
                        )
                    else:
                        logger.error(
                            "streams.group_create_failed",
                            stream=stream,
                            group=group_name,
                            error=str(e),
                        )
                        # Don't raise - continue with other groups
                        continue
        
        logger.info("streams.ensure_groups_completed")

    async def destroy_groups(self) -> None:
        """Destroy all consumer groups (use with caution)."""
        for stream in StreamName.ALL:
            try:
                groups = await self._redis.xinfo_groups(stream)
                for group in groups:
                    await self._redis.xgroup_destroy(stream, group["name"])
                    logger.info("streams.group_destroyed", stream=stream, group=group["name"])
            except Exception:
                pass

    # ── Write ───────────────────────────────────────────────

    async def append(
        self,
        stream: str,
        fields: dict[str, str],
    ) -> str:
        """Append an event to a stream.

        Returns the Redis-generated event ID (timestamp-sequence).
        """
        event_id = await self._redis.xadd(
            stream,
            fields,
            maxlen=100_000,  # cap stream at 100k entries
            approximate=True,
        )
        logger.debug("streams.appended", stream=stream, redis_id=event_id)
        return event_id

    # ── Read ────────────────────────────────────────────────

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, str]]]:
        """Read new messages from a consumer group.

        Returns list of (redis_id, fields_dict) tuples.
        Empty list if no new messages within block_ms.
        """
        try:
            results = await self._redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
        except Exception as e:
            logger.error(
                "streams.read_error",
                stream=stream,
                group=group,
                error=str(e),
            )
            return []

        messages: list[tuple[str, dict[str, str]]] = []
        for stream_name, entries in results:
            for redis_id, fields in entries:
                messages.append((redis_id, fields))
        return messages

    async def read_group_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        min_idle_ms: int = 30_000,
    ) -> list[tuple[str, dict[str, str]]]:
        """Read messages that were claimed by a consumer but not acknowledged.

        Used for crash recovery: reprocess messages idle for > min_idle_ms.
        """
        try:
            # First, claim idle messages
            claimed = await self._redis.xautoclaim(
                stream,
                group,
                consumer,
                min_idle_time=min_idle_ms,
                count=count,
            )
            # claimed is (next_start_id, messages, deleted_ids)
            messages = claimed[1] if len(claimed) > 1 else []
        except Exception as e:
            logger.error(
                "streams.autoclaim_error",
                stream=stream,
                group=group,
                error=str(e),
            )
            return []

        result: list[tuple[str, dict[str, str]]] = []
        for redis_id, fields in messages:
            result.append((redis_id, fields))
        return result

    # ── Acknowledge ─────────────────────────────────────────

    async def ack(
        self,
        stream: str,
        group: str,
        *event_ids: str,
    ) -> int:
        """Acknowledge one or more messages as processed.

        Returns the number of messages acknowledged.
        """
        if not event_ids:
            return 0
        count = await self._redis.xack(stream, group, *event_ids)
        logger.debug("streams.acked", stream=stream, group=group, count=count)
        return count

    # ── Dead Letter ─────────────────────────────────────────

    async def send_to_dlq(
        self,
        original_stream: str,
        redis_id: str,
        fields: dict[str, str],
        reason: str,
    ) -> str:
        """Move a message to the dead letter queue.

        Preserves original metadata and adds DLQ routing info.
        """
        fields["dlq_original_stream"] = original_stream
        fields["dlq_original_id"] = redis_id
        fields["dlq_reason"] = reason

        dlq_id = await self._redis.xadd(
            StreamName.DEAD_LETTER,
            fields,
            maxlen=50_000,
            approximate=True,
        )
        logger.warning(
            "streams.dlq_sent",
            original_stream=original_stream,
            original_id=redis_id,
            dlq_id=dlq_id,
            reason=reason,
        )
        return dlq_id

    # ── Stream Info ─────────────────────────────────────────

    async def stream_info(self, stream: str) -> dict[str, Any]:
        """Get length and metadata for a stream."""
        try:
            info = await self._redis.xinfo_stream(stream)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry", ""),
                "last_entry": info.get("last-entry", ""),
            }
        except Exception:
            return {"length": 0, "first_entry": "", "last_entry": ""}

    async def pending_info(self, stream: str, group: str) -> dict[str, Any]:
        """Get pending message count for a consumer group."""
        try:
            info = await self._redis.xpending(stream, group)
            return {
                "pending": info.get("pending", 0),
                "min_idle": info.get("min-idle", 0),
                "consumers": info.get("consumers", []),
            }
        except Exception:
            return {"pending": 0, "min_idle": 0, "consumers": []}

    # ── Trim ────────────────────────────────────────────────

    async def trim(self, stream: str, max_len: int = 100_000) -> int:
        """Trim a stream to max_len entries (approximate)."""
        removed = await self._redis.xtrim(stream, maxlen=max_len, approximate=True)
        if removed > 0:
            logger.info("streams.trimmed", stream=stream, removed=removed)
        return removed
