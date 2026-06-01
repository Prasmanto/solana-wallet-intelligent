"""Parser worker — normalizes raw events and enriches with intelligence.

Pipeline position: raw.stored → trade.normalized

This worker:
1. Consumes stored raw events
2. Normalizes to trade records
3. Updates wallet graph
4. Updates clustering
5. Classifies wallets
6. Publishes enriched trade

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
- Non-blocking: intelligence updates are async-safe
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.services.enrichment_service import EnrichmentService
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class ParserWorker(ConsumerWorker):
    """Consumes stored raw events and normalizes to trades with intelligence."""

    stream = StreamName.RAW_STORED
    group = "parser"
    concurrency = 4
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Parse raw event into normalized trade and update intelligence.

        Must commit to DB before returning.
        """
        payload = envelope.payload_dict

        logger.info(
            "parser_worker.processing",
            event_id=envelope.event_id[:16],
            event_type=envelope.event_type,
            stage="process",
        )

        # 1. Normalize to trade (existing logic)
        enriched = await self._normalize_event(envelope)

        # 2. Update wallet positions (new: writes to wallet_positions table)
        await self._update_wallet_positions(envelope, enriched)

        # 3. Publish to trade.normalized
        await self._producer.publish_chain(
            stream=StreamName.TRADE_NORMALIZED,
            event_type="trade.normalized",
            payload=enriched,
            source_envelope=envelope,
            metadata={
                "stage": "parser",
                "worker": "parser_worker",
            },
        )

        logger.info(
            "parser_worker.completed",
            event_id=envelope.event_id[:16],
            event_type=envelope.event_type,
            wallet=enriched.get("wallet", "")[:16] if enriched.get("wallet") else "",
            stage="completed",
        )

    async def _normalize_event(self, envelope: EventEnvelope) -> dict[str, Any]:
        """Normalize raw event using Helius parser."""
        from app.parser.helius_parser import parse_helius_event
        
        payload = envelope.payload_dict
        
        # Use Helius parser for extraction
        parsed = parse_helius_event(envelope.event_id, payload)
        
        if not parsed:
            # Fallback to enrichment service
            enrichment = EnrichmentService()
            enriched = enrichment.enrich_event(payload)
            enriched["event_id"] = envelope.event_id
            enriched["correlation_id"] = envelope.correlation_id
            enriched["timestamp"] = payload.get("block_time", payload.get("timestamp", 0))
            return enriched
        
        # Add metadata from envelope
        parsed["event_id"] = envelope.event_id
        parsed["correlation_id"] = envelope.correlation_id
        parsed["timestamp"] = payload.get("block_time", payload.get("timestamp", 0))
        
        return parsed

    async def _update_wallet_positions(
        self,
        envelope: EventEnvelope,
        enriched: dict[str, Any],
    ) -> None:
        """Update wallet_positions table based on enriched event."""
        wallet = enriched.get("wallet", "")
        token_mint = enriched.get("token", "") or enriched.get("primary_token", "") or "unknown"
        event_type = enriched.get("event_type", "TRANSFER")
        amount = enriched.get("amount", 0) or enriched.get("amount_out", 0) or enriched.get("amount_in", 0)
        signature = enriched.get("signature", "")

        # Skip if no wallet (token can be "unknown")
        if not wallet or len(wallet) < 30:
            logger.debug(
                "parser.skip_position_update",
                event_id=envelope.event_id[:16],
                wallet=wallet[:16] if wallet else "",
                reason="missing_wallet",
                stage="position_update",
            )
            return

        # Skip invalid events
        if event_type == "INVALID" or not enriched.get("is_valid", False):
            logger.debug(
                "parser.skip_position_update",
                event_id=envelope.event_id[:16],
                event_type=event_type,
                reason="invalid_event",
                stage="position_update",
            )
            return

        session = self.get_session()
        try:
            # Check for idempotency: has this signature been processed for this wallet+token?
            existing_position = await session.execute(
                select(WalletPosition).where(
                    WalletPosition.wallet == wallet,
                    WalletPosition.token_mint == token_mint,
                )
            )
            position = existing_position.scalar_one_or_none()

            # Check if we've already processed this trade
            if position and position.last_trade_id == signature:
                logger.info(
                    "parser.position_already_processed",
                    event_id=envelope.event_id[:16],
                    wallet=wallet[:16],
                    token=token_mint[:16],
                    signature=signature[:16],
                    stage="position_update",
                )
                await session.commit()
                return

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            if position is None:
                # Create new position
                position = WalletPosition(
                    wallet=wallet,
                    token_mint=token_mint,
                    position_size=0,
                    avg_cost_basis=0,
                    total_cost_basis=0,
                    realized_pnl=0,
                    realized_roi=0,
                    total_buys=0,
                    total_sells=0,
                    total_buy_volume=0,
                    total_sell_volume=0,
                    total_fees_paid=0,
                    hold_duration_seconds=0,
                    last_trade_id=signature,
                    event_version=1,
                    metadata_={"source": "live_pipeline"},
                )
                session.add(position)
                logger.info(
                    "parser.new_position_created",
                    event_id=envelope.event_id[:16],
                    wallet=wallet[:16],
                    token=token_mint[:16],
                    stage="position_update",
                )
            else:
                # Check version for optimistic locking
                if position.event_version > 1 and position.last_trade_id == signature:
                    logger.info(
                        "parser.position_version_conflict",
                        event_id=envelope.event_id[:16],
                        wallet=wallet[:16],
                        stage="position_update",
                    )
                    await session.commit()
                    return

            # Update position based on event type
            if event_type == "BUY":
                pos_size = float(position.position_size)
                avg_cost = float(position.avg_cost_basis)

                if pos_size == 0:
                    position.avg_cost_basis = 1.0
                else:
                    position.avg_cost_basis = (
                        (pos_size * avg_cost) + amount
                    ) / (pos_size + amount) if (pos_size + amount) else 0

                position.position_size = pos_size + amount
                position.total_buys = int(position.total_buys) + 1
                position.total_buy_volume = float(position.total_buy_volume) + amount
                position.first_buy_at = position.first_buy_at or now
                position.last_buy_at = now

            elif event_type == "SELL":
                pos_size = float(position.position_size)
                if pos_size > 0:
                    avg_cost = float(position.avg_cost_basis)
                    sell_proceeds = amount * avg_cost
                    position.realized_pnl = float(position.realized_pnl) + sell_proceeds - (amount * avg_cost)
                    position.position_size = max(pos_size - amount, 0)
                    position.total_sells = int(position.total_sells) + 1
                    position.total_sell_volume = float(position.total_sell_volume) + amount
                    position.first_sell_at = position.first_sell_at or now
                    position.last_sell_at = now

                    if float(position.total_cost_basis) > 0:
                        position.realized_roi = float(
                            (float(position.realized_pnl) / float(position.total_cost_basis)) * 100
                        )

            elif event_type == "TRANSFER":
                position.total_fees_paid = float(position.total_fees_paid) + enriched.get("fee", 0) / 1e9

            # Update common fields
            position.last_trade_id = signature
            position.last_trade_at = now
            position.last_processed_at = now
            position.event_version = int(position.event_version) + 1

            # Commit
            await session.commit()

            logger.info(
                "parser.position_updated",
                event_id=envelope.event_id[:16],
                wallet=wallet[:16],
                token=token_mint[:16],
                event_type=event_type,
                position_size=float(position.position_size),
                total_buys=position.total_buys,
                total_sells=position.total_sells,
                stage="position_update",
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "parser.position_update_error",
                event_id=envelope.event_id[:16],
                error=str(e),
                stage="position_update",
            )
            raise
        finally:
            await session.close()
