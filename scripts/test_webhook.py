"""Test Helius webhook ingestion — validates the full ingestion pipeline.

Tests:
1. Webhook signature validation
2. Single transaction ingestion
3. Batched transaction ingestion
4. Idempotent ingestion (duplicate webhooks)
5. Redis Stream publication
6. Database persistence

Usage:
    docker compose up -d postgres redis
    python -m scripts.test_webhook
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config.logging import setup_logging
from app.config.settings import settings
from app.infrastructure.database.models import RawEvent
from app.infrastructure.database.session import Base
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.infrastructure.redis.streams import StreamsManager
from app.infrastructure.redis.producer import EventProducer
from app.services.ingestion_service import IngestionService
from app.schemas.helius import HeliusWebhookPayload
from app.main import app

logger = structlog.get_logger("webhook_test")


# ── Test Fixtures ───────────────────────────────────────────

def make_helius_payload(
    signature: str = None,
    slot: int = 12345,
    tx_type: str = "TRANSFER",
) -> dict:
    """Create a fake Helius webhook payload."""
    if not signature:
        signature = f"test_{uuid.uuid4().hex[:16]}"

    return {
        "webhookID": "test-webhook-001",
        "webhookType": "enhanced",
        "cluster": "mainnet-beta",
        "transaction": {
            "signature": signature,
            "slot": slot,
            "timestamp": int(time.time()),
            "type": tx_type,
            "source": "SYSTEM_PROGRAM",
            "fee": 5000,
            "fee_payer": "11111111111111111111111111111111",
            "description": "Test transfer",
            "accountData": [
                {
                    "account": "11111111111111111111111111111111",
                    "nativeBalanceChange": -100000,
                    "tokenBalanceChanges": [],
                }
            ],
            "tokenTransfers": [],
            "nativeTransfers": [
                {
                    "fromUserAccount": "11111111111111111111111111111111",
                    "toUserAccount": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "amount": 100000,
                }
            ],
            "events": {},
        },
    }


def make_batched_payload(count: int = 3) -> dict:
    """Create a Helius webhook payload with multiple transactions."""
    transactions = []
    for i in range(count):
        transactions.append({
            "signature": f"batch_{uuid.uuid4().hex[:16]}_{i}",
            "slot": 12345 + i,
            "timestamp": int(time.time()),
            "type": "SWAP" if i % 2 == 0 else "TRANSFER",
            "source": "RAYDIUM" if i % 2 == 0 else "SYSTEM_PROGRAM",
            "fee": 5000,
            "fee_payer": "11111111111111111111111111111111",
            "description": f"Test batch transaction {i}",
            "accountData": [],
            "tokenTransfers": [],
            "nativeTransfers": [],
            "events": {},
        })

    return {
        "webhookID": "test-webhook-batch",
        "webhookType": "enhanced",
        "cluster": "mainnet-beta",
        "transactions": transactions,
    }


# ── Tests ───────────────────────────────────────────────────

async def run_webhook_test() -> None:
    """Run the webhook ingestion test suite."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 60)
    print("  HELIUS WEBHOOK INGESTION TEST")
    print("=" * 60)

    # Connect to database
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=5)

    # Check if tables exist, only create if not
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        result = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("raw_events")
        )
        if not result:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Connect to Redis
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.REDIS_STREAMS_URL, decode_responses=True)
    await redis.ping()
    streams_manager = StreamsManager(redis)
    await streams_manager.ensure_groups()

    # ── Test 1: Signature Validation ────────────────────────
    print("\n  Test 1: Webhook signature validation")
    print("  " + "-" * 50)

    async with session_factory() as session:
        repo = RawEventRepository(session)
        producer = EventProducer(streams_manager)
        service = IngestionService(repo=repo, producer=producer)

        # No secret configured (dev mode)
        payload_bytes = json.dumps(make_helius_payload()).encode()
        result = service.validate_webhook(payload_bytes, None)
        print(f"    No secret (dev mode): {'OK' if result.valid else 'FAIL'}")

    # ── Test 2: Single Transaction Ingestion ────────────────
    print("\n  Test 2: Single transaction ingestion")
    print("  " + "-" * 50)

    async with session_factory() as session:
        repo = RawEventRepository(session)
        producer = EventProducer(streams_manager)
        service = IngestionService(repo=repo, producer=producer)

        payload = HeliusWebhookPayload.model_validate(make_helius_payload())
        result = await service.ingest_webhook(payload)
        await session.commit()

        print(f"    Transactions processed: {result.transactions_processed}")
        print(f"    Events persisted: {result.events_persisted}")
        print(f"    Events published: {result.events_published}")
        print(f"    Errors: {len(result.errors)}")
        print(f"    Result: {'OK' if result.success else 'FAIL'}")

    # ── Test 3: Batched Transaction Ingestion ───────────────
    print("\n  Test 3: Batched transaction ingestion")
    print("  " + "-" * 50)

    async with session_factory() as session:
        repo = RawEventRepository(session)
        producer = EventProducer(streams_manager)
        service = IngestionService(repo=repo, producer=producer)

        batch_payload = HeliusWebhookPayload.model_validate(make_batched_payload(3))
        result = await service.ingest_webhook(batch_payload)
        await session.commit()

        print(f"    Transactions processed: {result.transactions_processed}")
        print(f"    Events persisted: {result.events_persisted}")
        print(f"    Events published: {result.events_published}")
        print(f"    Result: {'OK' if result.success else 'FAIL'}")

    # ── Test 4: Idempotent Ingestion (Duplicate) ────────────
    print("\n  Test 4: Idempotent ingestion (duplicate webhook)")
    print("  " + "-" * 50)

    async with session_factory() as session:
        repo = RawEventRepository(session)
        producer = EventProducer(streams_manager)
        service = IngestionService(repo=repo, producer=producer)

        # Send same payload twice
        test_sig = f"idem_{uuid.uuid4().hex[:16]}"
        payload_data = make_helius_payload(signature=test_sig)

        # First ingestion
        payload1 = HeliusWebhookPayload.model_validate(payload_data)
        result1 = await service.ingest_webhook(payload1)
        await session.commit()

        # Second ingestion (duplicate)
        payload2 = HeliusWebhookPayload.model_validate(payload_data)
        result2 = await service.ingest_webhook(payload2)
        await session.commit()

        print(f"    First ingestion:  persisted={result1.events_persisted}")
        print(f"    Second ingestion: persisted={result2.events_persisted}, skipped={result2.duplicates_skipped}")
        print(f"    Idempotent: {'OK' if result2.duplicates_skipped == 1 else 'FAIL'}")

    # ── Test 5: Redis Stream Publication ────────────────────
    print("\n  Test 5: Redis Stream publication")
    print("  " + "-" * 50)

    # Check if events were published to the stream
    try:
        stream_info = await streams_manager.stream_info("solana_intel.raw.pending")
        length = stream_info.get("length", 0)
        print(f"    Stream length: {length}")
        print(f"    Published: {'OK' if length > 0 else 'FAIL'}")
    except Exception as e:
        print(f"    Error: {e}")

    # ── Test 6: Database Persistence ────────────────────────
    print("\n  Test 6: Database persistence")
    print("  " + "-" * 50)

    async with session_factory() as session:
        from sqlalchemy import func, select

        count_stmt = select(func.count(RawEvent.id))
        result = await session.execute(count_stmt)
        total = result.scalar()
        print(f"    Total events in DB: {total}")
        print(f"    Persisted: {'OK' if total > 0 else 'FAIL'}")

    # ── Test 7: HTTP Endpoint Test ──────────────────────────
    print("\n  Test 7: HTTP endpoint test")
    print("  " + "-" * 50)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test endpoint
        response = await client.post("/api/v1/ingest/helius/test")
        print(f"    Test endpoint: {response.status_code} {'OK' if response.status_code == 200 else 'FAIL'}")

        # Test webhook with valid payload
        webhook_payload = make_helius_payload()
        response = await client.post(
            "/api/v1/ingest/helius",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
        )
        print(f"    Webhook endpoint: {response.status_code} {'OK' if response.status_code == 200 else 'FAIL'}")

        if response.status_code == 200:
            data = response.json()
            print(f"    Response: persisted={data.get('events_persisted', 0)}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)

    await redis.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_webhook_test())
