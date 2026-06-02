"""Test script to verify the live pipeline works correctly.

This script sends a test webhook event through the pipeline and verifies:
1. Event is stored in raw_events table
2. Wallet position is created in wallet_positions table
3. Event flows through Redis Streams

Usage:
    python -m scripts.test_live_pipeline
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import structlog

from app.config.settings import settings
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.infrastructure.redis.manager import RedisManager
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager
from app.core.domain.stream_names import StreamName
from app.services.ingestion_service import IngestionService
from app.schemas.helius import HeliusWebhookPayload, WebhookTransaction

logger = structlog.get_logger(__name__)


async def test_live_pipeline():
    """Test the live pipeline with a sample webhook event."""
    logger.info("test.starting_pipeline_test")

    # 1. Initialize database
    db_manager = DatabaseManager(settings)
    await db_manager.connect()
    logger.info("test.database_connected")

    # 2. Initialize Redis
    redis_manager = RedisManager(settings)
    await redis_manager.connect()
    logger.info("test.redis_connected")

    streams_redis = redis_manager.get_client("streams")
    streams_manager = StreamsManager(streams_redis)
    producer = EventProducer(streams_manager)

    # 3. Ensure consumer groups exist
    await streams_manager.ensure_groups()
    logger.info("test.consumer_groups_ready")

    # 4. Create test webhook payload
    test_signature = f"test_signature_{uuid.uuid4().hex[:8]}"
    test_wallet = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    test_token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC

    test_event = {
        "signature": test_signature,
        "slot": 12345678,
        "type": "SWAP",
        "source": "RAYDIUM",
        "fee": 5000,
        "fee_payer": test_wallet,
        "description": f"Test swap on Raydium",
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
        "token_transfers": [],
        "native_transfers": [],
        "account_data": [],
        "events": {},
        "data": {
            "from": test_wallet,
            "token_in": "So11111111111111111111111111111111111111112",  # SOL
            "token_out": test_token,
            "amount_in": 1000000000,  # 1 SOL in lamports
            "amount_out": 1000000,  # 1 USDC (6 decimals)
        },
    }

    # 5. Create Helius payload
    webhook_payload = HeliusWebhookPayload(
        transactions=[WebhookTransaction.model_validate(test_event)],
    )

    # 6. Create ingestion service
    session = db_manager.get_session()
    try:
        repo = RawEventRepository(session)
        ingestion_service = IngestionService(repo=repo, producer=producer)

        # 7. Ingest the webhook
        result = await ingestion_service.ingest_webhook(webhook_payload)
        logger.info(
            "test.webhook_ingested",
            success=result.success,
            transactions_processed=result.transactions_processed,
            events_persisted=result.events_persisted,
            events_published=result.events_published,
        )

        # 8. Wait a moment for async processing
        await asyncio.sleep(1)

        # 9. Check if event was stored in raw_events
        from sqlalchemy import select, func
        from app.infrastructure.database.models.raw_event import RawEvent

        async with db_manager.get_session() as check_session:
            # Count events
            count_result = await check_session.execute(
                select(func.count(RawEvent.id))
            )
            event_count = count_result.scalar()
            logger.info("test.raw_events_count", count=event_count)

            # Get the latest event
            latest_result = await check_session.execute(
                select(RawEvent)
                .where(RawEvent.event_id.like(f"%{test_signature[:16]}%"))
                .limit(1)
            )
            latest_event = latest_result.scalar_one_or_none()
            if latest_event:
                logger.info(
                    "test.latest_event_found",
                    event_id=latest_event.event_id[:16],
                    status=latest_event.status,
                    event_type=latest_event.event_type,
                )
            else:
                logger.warning("test.no_latest_event_found")

        # 10. Check wallet_positions table
        from app.infrastructure.database.models.wallet_position import WalletPosition

        async with db_manager.get_session() as position_session:
            position_result = await position_session.execute(
                select(WalletPosition).where(
                    WalletPosition.wallet == test_wallet
                ).limit(1)
            )
            position = position_result.scalar_one_or_none()
            if position:
                logger.info(
                    "test.wallet_position_found",
                    wallet=position.wallet[:16],
                    token=position.token_mint[:16],
                    position_size=float(position.position_size),
                    total_buys=position.total_buys,
                )
            else:
                logger.info("test.no_wallet_position_found_yet")

        # 11. Check Redis streams
        stream_info = await streams_manager.stream_info(StreamName.RAW_PENDING)
        logger.info("test.raw_pending_stream", length=stream_info.get("length", 0))

        stream_info = await streams_manager.stream_info(StreamName.RAW_STORED)
        logger.info("test.raw_stored_stream", length=stream_info.get("length", 0))

        logger.info("test.pipeline_test_completed")

    finally:
        await session.close()
        await redis_manager.close()
        await db_manager.close()

    return result


if __name__ == "__main__":
    asyncio.run(test_live_pipeline())
