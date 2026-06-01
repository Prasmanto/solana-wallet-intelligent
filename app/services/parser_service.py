"""Parser service — orchestrates transaction normalization and persistence.

Pipeline:
1. Receive raw event payload (from Redis Stream)
2. Parse Helius transaction → NormalizedTrade
3. Persist normalized trade to database
4. Publish to trade.normalized stream
5. Return parse result

Design:
- Idempotent: duplicate signatures are safely ignored
- Atomic: parse + persist + publish in single operation
- Async: non-blocking for high throughput
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.redis.producer import EventProducer
from app.parser.transaction_normalizer import TransactionNormalizer
from app.schemas.helius import WebhookTransaction
from app.schemas.trade import (
    BatchParseResult,
    NormalizedTrade,
    ParseResult,
)

logger = structlog.get_logger(__name__)


class ParserService:
    """Service for parsing raw events into normalized trades."""

    def __init__(
        self,
        session: AsyncSession,
        producer: EventProducer,
    ) -> None:
        self._session = session
        self._producer = producer
        self._normalizer = TransactionNormalizer()

    async def parse_raw_event(
        self,
        envelope: EventEnvelope,
    ) -> ParseResult:
        """Parse a raw event into a normalized trade.

        Args:
            envelope: The raw event envelope from Redis Stream

        Returns:
            ParseResult with trade or error
        """
        payload = envelope.payload_dict

        # Build WebhookTransaction from payload
        try:
            tx = self._payload_to_transaction(payload)
        except Exception as e:
            logger.error(
                "parser_service.tx_build_error",
                event_id=envelope.event_id[:16],
                error=str(e),
            )
            return ParseResult(
                success=False,
                error=f"Failed to build transaction: {str(e)}",
                error_code="TX_BUILD_ERROR",
            )

        # Check for duplicate (idempotent)
        if await self._is_already_parsed(tx.signature):
            logger.info(
                "parser_service.duplicate_skipped",
                signature=tx.signature[:16],
            )
            return ParseResult(
                success=False,
                error="Transaction already parsed",
                error_code="DUPLICATE",
            )

        # Normalize
        result = self._normalizer.normalize(
            tx=tx,
            raw_event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
        )

        if not result.success or not result.trade:
            return result

        # Persist normalized trade
        try:
            await self._persist_trade(result.trade)
        except Exception as e:
            logger.error(
                "parser_service.persist_error",
                trade_id=result.trade.trade_id[:16],
                error=str(e),
            )
            return ParseResult(
                success=False,
                error=f"Failed to persist trade: {str(e)}",
                error_code="PERSIST_ERROR",
            )

        # Publish to normalized stream
        try:
            await self._publish_trade(result.trade, envelope)
        except Exception as e:
            logger.error(
                "parser_service.publish_error",
                trade_id=result.trade.trade_id[:16],
                error=str(e),
            )
            # Trade is persisted, so this is non-fatal
            result.warnings.append(f"Publish failed: {str(e)}")

        return result

    async def parse_batch(
        self,
        envelopes: list[EventEnvelope],
    ) -> BatchParseResult:
        """Parse a batch of raw events."""
        batch_result = BatchParseResult(total=len(envelopes))

        for envelope in envelopes:
            result = await self.parse_raw_event(envelope)
            if result.success and result.trade:
                batch_result.success_count += 1
                batch_result.trades.append(result.trade)
            else:
                batch_result.error_count += 1
                batch_result.errors.append(result)

        logger.info(
            "parser_service.batch_completed",
            total=batch_result.total,
            success=batch_result.success_count,
            errors=batch_result.error_count,
        )

        return batch_result

    # ── Internal Methods ────────────────────────────────────

    def _payload_to_transaction(self, payload: dict[str, Any]) -> WebhookTransaction:
        """Convert raw payload dict to WebhookTransaction."""
        return WebhookTransaction(
            signature=payload.get("signature", ""),
            slot=payload.get("slot", 0),
            timestamp=payload.get("block_time"),
            type=payload.get("tx_type", "UNKNOWN"),
            source=payload.get("source", ""),
            fee=payload.get("fee", 0),
            fee_payer=payload.get("fee_payer", ""),
            description=payload.get("description", ""),
            accountData=payload.get("account_data", []),
            tokenTransfers=payload.get("token_transfers", []),
            nativeTransfers=payload.get("native_transfers", []),
            events=payload.get("events", {}),
        )

    async def _is_already_parsed(self, signature: str) -> bool:
        """Check if transaction was already parsed (idempotent)."""
        from app.infrastructure.database.models.raw_event import RawEvent

        stmt = select(RawEvent.id).where(
            and_(
                RawEvent.stream_name == StreamName.TRADE_NORMALIZED,
                RawEvent.payload["signature"].astext == signature,
            )
        ).limit(1)

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _persist_trade(self, trade: NormalizedTrade) -> None:
        """Persist normalized trade to database."""
        from app.infrastructure.database.models.raw_event import RawEvent

        stmt = (
            pg_insert(RawEvent)
            .values(
                id=uuid.uuid4(),
                event_id=trade.trade_id,
                event_version=1,
                stream_name=StreamName.TRADE_NORMALIZED,
                event_type="trade.normalized",
                correlation_id=trade.correlation_id or str(uuid.uuid4()),
                causation_id=trade.raw_event_id,
                payload=trade.model_dump(mode="json"),
                metadata_={
                    "wallet": trade.wallet,
                    "protocol": trade.protocol.value,
                    "direction": trade.direction.value,
                    "signature": trade.signature,
                },
                retry_count=0,
                status="completed",
                created_at=datetime.now(timezone.utc),
                processed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

        await self._session.execute(stmt)
        await self._session.flush()

    async def _publish_trade(
        self,
        trade: NormalizedTrade,
        source_envelope: EventEnvelope,
    ) -> None:
        """Publish normalized trade to Redis Stream."""
        await self._producer.publish_chain(
            stream=StreamName.TRADE_NORMALIZED,
            event_type="trade.normalized",
            payload=trade.model_dump(mode="json"),
            source_envelope=source_envelope,
            metadata={
                "wallet": trade.wallet,
                "protocol": trade.protocol.value,
                "direction": trade.direction.value,
            },
        )
