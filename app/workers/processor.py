"""Event processor — handles idempotency, retry, and DLQ logic.

Production-grade processor with:
- DB-level idempotency check
- ACK only after successful commit
- Retry with exponential backoff
- DLQ routing after max retries
- Structured logging at every stage
"""

from __future__ import annotations

import time
from typing import Any, Callable, Awaitable

import structlog

from app.config.metrics import (
    EVENT_DLQ_TOTAL,
    EVENT_PROCESSING_DURATION,
    EVENT_RETRY_TOTAL,
    EVENTS_TOTAL,
)
from app.core.domain.events import EventEnvelope
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager

logger = structlog.get_logger(__name__)


class EventProcessor:
    """Handles event processing with idempotency, retry, and DLQ."""

    def __init__(
        self,
        streams: StreamsManager,
        producer: EventProducer,
        worker_name: str,
        stream: str,
        group: str,
        max_retries: int = 5,
    ) -> None:
        self._streams = streams
        self._producer = producer
        self._worker_name = worker_name
        self._stream = stream
        self._group = group
        self._max_retries = max_retries

    async def process_event(
        self,
        redis_id: str,
        envelope: EventEnvelope,
        handler: Callable[[EventEnvelope], Awaitable[None]],
        idempotency_check: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        """Process an event with full guarantees.

        Flow:
        1. Check idempotency (if check provided)
        2. If already processed → skip + ACK
        3. Process event
        4. ACK only after success
        5. On failure → retry or DLQ
        """
        structlog.contextvars.bind_contextvars(
            correlation_id=envelope.correlation_id,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            worker=self._worker_name,
        )

        start_time = time.time()

        try:
            # Step 1: Idempotency check
            if idempotency_check:
                already_processed = await idempotency_check(envelope.event_id)
                if already_processed:
                    await self._streams.ack(self._stream, self._group, redis_id)
                    EVENTS_TOTAL.labels(
                        stream=self._stream,
                        event_type=envelope.event_type,
                        status="skipped",
                    ).inc()
                    logger.info(
                        "processor.event_skipped",
                        redis_id=redis_id,
                        reason="already_processed",
                        stage="skip",
                    )
                    return

            # Step 2: Process event
            await handler(envelope)

            # Step 3: ACK after successful DB commit
            await self._streams.ack(self._stream, self._group, redis_id)

            duration = time.time() - start_time
            EVENTS_TOTAL.labels(
                stream=self._stream,
                event_type=envelope.event_type,
                status="success",
            ).inc()
            EVENT_PROCESSING_DURATION.labels(
                stream=self._stream,
                worker=self._worker_name,
            ).observe(duration)

            logger.info(
                "processor.event_processed",
                redis_id=redis_id,
                retry_count=envelope.retry_count,
                duration_ms=round(duration * 1000, 2),
                stage="ack",
            )

        except Exception as e:
            duration = time.time() - start_time
            EVENTS_TOTAL.labels(
                stream=self._stream,
                event_type=envelope.event_type,
                status="failed",
            ).inc()

            if envelope.is_retryable:
                # Retry
                retried = envelope.increment_retry()
                await self._producer.republish(
                    stream=self._stream,
                    envelope=retried,
                )
                await self._streams.ack(self._stream, self._group, redis_id)

                EVENT_RETRY_TOTAL.labels(
                    stream=self._stream,
                    worker=self._worker_name,
                ).inc()

                logger.warning(
                    "processor.event_retried",
                    redis_id=redis_id,
                    retry_count=retried.retry_count,
                    max_retries=retried.max_retries,
                    error=str(e),
                    stage="retry",
                )
            else:
                # DLQ
                await self._streams.send_to_dlq(
                    original_stream=self._stream,
                    redis_id=redis_id,
                    fields=envelope.to_dict(),
                    reason=f"max_retries_exceeded: {e}",
                )
                await self._streams.ack(self._stream, self._group, redis_id)

                EVENT_DLQ_TOTAL.labels(
                    stream=self._stream,
                    worker=self._worker_name,
                    reason="max_retries",
                ).inc()

                logger.error(
                    "processor.event_dead_lettered",
                    redis_id=redis_id,
                    retry_count=envelope.retry_count,
                    error=str(e),
                    stage="dlq",
                )

        finally:
            structlog.contextvars.unbind_contextvars(
                "correlation_id", "event_id", "event_type", "worker"
            )


class IdempotencyGuard:
    """DB-level idempotency check using event_id."""

    def __init__(self, check_fn: Callable[[str], Awaitable[bool]]) -> None:
        self._check_fn = check_fn

    async def is_processed(self, event_id: str) -> bool:
        """Check if event was already processed in DB."""
        return await self._check_fn(event_id)
