"""Event producer — publishes events to Redis Streams.

Wraps the StreamsManager with:
- Automatic EventEnvelope creation
- Correlation ID propagation
- Structured logging
- Fire-and-forget + awaitable modes
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.domain.events import EventEnvelope
from app.infrastructure.redis.streams import StreamsManager

logger = structlog.get_logger(__name__)


class EventProducer:
    """Publishes typed events to Redis Streams."""

    def __init__(self, streams: StreamsManager) -> None:
        self._streams = streams

    async def publish(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        causation_id: str | None = None,
        max_retries: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create an EventEnvelope and publish to the given stream.

        Returns the Redis stream ID.

        Usage:
            await producer.publish(
                stream=StreamName.RAW_PENDING,
                event_type="raw.received",
                payload={"signature": "...", "slot": 12345},
                metadata={"source": "solana_ws"},
            )
        """
        envelope = EventEnvelope.create(
            event_type=event_type,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            max_retries=max_retries,
            metadata=metadata,
        )

        redis_id = await self._streams.append(
            stream=stream,
            fields=envelope.to_dict(),
        )

        logger.info(
            "event.published",
            event_type=event_type,
            stream=stream,
            correlation_id=envelope.correlation_id,
            event_id=envelope.event_id,
            redis_id=redis_id,
        )

        return redis_id

    async def publish_chain(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        source_envelope: EventEnvelope,
        max_retries: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Publish a new event that is causally linked to a source event.

        Propagates the correlation_id and sets causation_id to the source's event_id.
        This creates a traceable chain through the pipeline.
        """
        envelope = EventEnvelope.create(
            event_type=event_type,
            payload=payload,
            correlation_id=source_envelope.correlation_id,
            causation_id=source_envelope.event_id,
            max_retries=max_retries,
            metadata={
                **(metadata or {}),
                "source_event_type": source_envelope.event_type,
            },
        )

        redis_id = await self._streams.append(
            stream=stream,
            fields=envelope.to_dict(),
        )

        logger.info(
            "event.published_chain",
            event_type=event_type,
            stream=stream,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            redis_id=redis_id,
        )

        return redis_id

    async def republish(
        self,
        *,
        stream: str,
        envelope: EventEnvelope,
    ) -> str:
        """Republish an existing envelope (e.g., after retry increment)."""
        redis_id = await self._streams.append(
            stream=stream,
            fields=envelope.to_dict(),
        )
        logger.debug(
            "event.republished",
            event_type=envelope.event_type,
            stream=stream,
            retry_count=envelope.retry_count,
            redis_id=redis_id,
        )
        return redis_id
