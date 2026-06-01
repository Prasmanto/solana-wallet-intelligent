"""Ingestion worker — validates and stores raw Solana events.

Pipeline position: raw.pending → raw.stored

Production guarantees:
- Idempotent: event_id checked in DB before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
- Structured logging at every stage
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.models.raw_event import RawEvent
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class IngestionWorker(ConsumerWorker):
    """Consumes raw events, validates them, and stores to DB."""

    stream = StreamName.RAW_PENDING
    group = "ingestion"
    concurrency = 4
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Validate and store a raw event.

        Must commit to DB before returning (ACK guarantee).
        """
        payload = envelope.payload_dict

        logger.info(
            "ingestion.processing",
            event_id=envelope.event_id[:16],
            signature=payload.get("signature", "")[:16] if payload.get("signature") else "unknown",
            stage="process",
        )

        # 1. Create database session
        session = self.get_session()
        try:
            repo = RawEventRepository(session)

            # 2. Check if event was already fully processed (idempotency)
            existing = await repo.get_by_event_id(envelope.event_id)
            if existing and existing.status == "completed":
                logger.info(
                    "ingestion.event_already_exists",
                    event_id=envelope.event_id[:16],
                    status=existing.status,
                    stage="skip",
                )
                await session.commit()
                return

            # 3. Store or update raw_events table
            metadata = {
                "source": "helius_webhook",
                "correlation_id": envelope.correlation_id,
                "event_type": envelope.event_type,
                "timestamp": envelope.timestamp,
            }

            if existing and existing.status in ("pending", "processing"):
                await repo.mark_processing(envelope.event_id)
                logger.info(
                    "ingestion.event_marked_processing",
                    event_id=envelope.event_id[:16],
                    status=existing.status,
                    stage="persist",
                )
            else:
                persisted = await repo.insert(
                    event_id=envelope.event_id,
                    stream_name=StreamName.RAW_PENDING,
                    event_type="raw.received",
                    correlation_id=envelope.correlation_id,
                    payload=payload,
                    metadata=metadata,
                    retry_count=envelope.retry_count,
                    status="processing",
                )

                if not persisted:
                    logger.warning(
                        "ingestion.insert_failed",
                        event_id=envelope.event_id[:16],
                        stage="persist",
                    )
                    await session.commit()
                    return

            # 4. Commit to DB
            await session.commit()

            logger.info(
                "ingestion.event_stored",
                event_id=envelope.event_id[:16],
                signature=payload.get("signature", "")[:16] if payload.get("signature") else "unknown",
                stage="persist",
            )

            # 5. Publish to RAW_STORED stream (after successful DB commit)
            await self._producer.publish_chain(
                stream=StreamName.RAW_STORED,
                event_type="raw.stored",
                payload=payload,
                source_envelope=envelope,
                metadata={
                    "stage": "ingestion",
                    "worker": "ingestion_worker",
                    "event_id": envelope.event_id,
                },
            )

            # 6. Mark as completed in DB
            await repo.mark_completed(envelope.event_id)
            await session.commit()

            logger.info(
                "ingestion.event_completed",
                event_id=envelope.event_id[:16],
                signature=payload.get("signature", "")[:16] if payload.get("signature") else "unknown",
                stage="completed",
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "ingestion.processing_error",
                event_id=envelope.event_id[:16],
                error=str(e),
                stage="error",
            )
            raise
        finally:
            await session.close()

    async def _check_idempotent(self, event_id: str) -> bool:
        """Check if event was already processed in DB."""
        if not self._session_factory:
            return False

        session = self.get_session()
        try:
            repo = RawEventRepository(session)
            existing = await repo.get_by_event_id(event_id)
            return existing is not None and existing.status == "completed"
        finally:
            await session.close()
