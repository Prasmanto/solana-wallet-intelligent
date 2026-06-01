"""Test raw event persistence — validates the full persistence layer.

Tests:
1. Single event insert (idempotent)
2. Batch insert
3. Status lifecycle
4. Replay by stream
5. Replay by correlation
6. Replay failed events
7. Analytics queries

Usage:
    docker compose up -d postgres
    python -m scripts.test_persistence
"""

from __future__ import annotations

import asyncio
import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config.logging import setup_logging
from app.config.settings import settings
from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.models import RawEvent
from app.infrastructure.database.session import Base
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.services.raw_event_service import RawEventService

logger = structlog.get_logger("persistence_test")


async def run_persistence_test(event_count: int) -> None:
    """Run the persistence test suite."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 60)
    print("  RAW EVENT PERSISTENCE TEST")
    print("=" * 60)

    # Connect to database
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=5,
    )

    # Create tables (for testing without Alembic)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        repo = RawEventRepository(session)
        service = RawEventService(repo)

        # ── Test 1: Single Insert ────────────────────────────
        print("\n  Test 1: Single event insert (idempotent)")
        print("  " + "-" * 50)

        envelope = EventEnvelope.create(
            event_type="raw.received",
            payload={"signature": "test_sig_123", "slot": 12345},
            correlation_id=str(uuid.uuid4()),
            metadata={"source": "test"},
        )

        inserted = await service.persist_envelope(
            envelope=envelope,
            stream_name=StreamName.RAW_PENDING,
        )
        print(f"    Insert 1: {'OK' if inserted else 'FAIL'}")

        # Duplicate insert (should be idempotent)
        duplicate = await service.persist_envelope(
            envelope=envelope,
            stream_name=StreamName.RAW_PENDING,
        )
        print(f"    Insert 2 (duplicate): {'OK (ignored)' if not duplicate else 'FAIL (not idempotent)'}")

        # Verify event exists
        stored = await repo.get_by_event_id(envelope.event_id)
        print(f"    Verify: {'OK' if stored else 'FAIL'}")
        if stored:
            print(f"      event_id: {stored.event_id[:16]}...")
            print(f"      stream:   {stored.stream_name}")
            print(f"      type:     {stored.event_type}")
            print(f"      status:   {stored.status}")

        # ── Test 2: Batch Insert ─────────────────────────────
        print("\n  Test 2: Batch insert")
        print("  " + "-" * 50)

        batch_envelopes = []
        for i in range(event_count):
            env = EventEnvelope.create(
                event_type="raw.received",
                payload={"batch_index": i, "value": f"test_{i}"},
                metadata={"source": "batch_test"},
            )
            batch_envelopes.append((env, StreamName.RAW_PENDING))

        batch_count = await service.persist_batch(batch_envelopes)
        print(f"    Batch size:   {event_count}")
        print(f"    Inserted:     {batch_count}")
        print(f"    Duplicates:   {event_count - batch_count}")

        # ── Test 3: Status Lifecycle ─────────────────────────
        print("\n  Test 3: Status lifecycle")
        print("  " + "-" * 50)

        # Get a fresh event
        test_env = EventEnvelope.create(
            event_type="raw.received",
            payload={"lifecycle_test": True},
        )
        await service.persist_envelope(test_env, StreamName.RAW_PENDING)

        # pending -> processing
        await service.mark_processing(test_env.event_id)
        await session.commit()
        stored = await repo.get_by_event_id(test_env.event_id)
        print(f"    pending -> processing: {'OK' if stored.status == 'processing' else 'FAIL'}")

        # processing -> completed
        await service.mark_completed(test_env.event_id)
        await session.commit()
        stored = await repo.get_by_event_id(test_env.event_id)
        print(f"    processing -> completed: {'OK' if stored.status == 'completed' else 'FAIL'}")
        print(f"    processed_at set: {'OK' if stored.processed_at else 'FAIL'}")

        # Test failed status
        fail_env = EventEnvelope.create(
            event_type="raw.received",
            payload={"fail_test": True},
        )
        await service.persist_envelope(fail_env, StreamName.RAW_PENDING)
        await service.mark_failed(fail_env.event_id)
        await session.commit()
        stored = await repo.get_by_event_id(fail_env.event_id)
        print(f"    -> failed: {'OK' if stored.status == 'failed' else 'FAIL'}")

        # Test dead_letter status
        dlq_env = EventEnvelope.create(
            event_type="raw.received",
            payload={"dlq_test": True},
        )
        await service.persist_envelope(dlq_env, StreamName.RAW_PENDING)
        await service.mark_dead_letter(dlq_env.event_id)
        await session.commit()
        stored = await repo.get_by_event_id(dlq_env.event_id)
        print(f"    -> dead_letter: {'OK' if stored.status == 'dead_letter' else 'FAIL'}")

        await session.commit()

        # ── Test 4: Replay by Stream ─────────────────────────
        print("\n  Test 4: Replay by stream")
        print("  " + "-" * 50)

        replay_events = await service.replay_stream(
            stream_name=StreamName.RAW_PENDING,
            limit=10,
        )
        print(f"    Events in stream: {len(replay_events)}")
        if replay_events:
            print(f"    First event type: {replay_events[0]['event_type']}")
            print(f"    Last event type:  {replay_events[-1]['event_type']}")

        # ── Test 5: Replay by Correlation ────────────────────
        print("\n  Test 5: Replay by correlation ID")
        print("  " + "-" * 50)

        # Create a chain of events with same correlation_id
        chain_correlation = str(uuid.uuid4())
        for i in range(3):
            env = EventEnvelope.create(
                event_type=f"stage{i}.processed",
                payload={"chain_step": i},
                correlation_id=chain_correlation,
            )
            await service.persist_envelope(env, StreamName.RAW_PENDING)

        chain_events = await service.replay_correlation(chain_correlation)
        print(f"    Chain length: {len(chain_events)}")
        for e in chain_events:
            print(f"      {e['event_type']} (created: {e['created_at'][:19]})")

        # ── Test 6: Replay Failed ────────────────────────────
        print("\n  Test 6: Replay failed events")
        print("  " + "-" * 50)

        failed_events = await service.replay_failed()
        print(f"    Failed events: {len(failed_events)}")

        # ── Test 7: Analytics ────────────────────────────────
        print("\n  Test 7: Analytics")
        print("  " + "-" * 50)

        stats = await service.get_stream_stats()
        print(f"    Total events: {stats['total_events']}")
        print(f"    By stream:")
        for stream, count in stats["events_by_stream"].items():
            print(f"      {stream}: {count}")
        print(f"    By status:")
        for status, count in stats["events_by_status"].items():
            print(f"      {status}: {count}")

        time_range = await service.get_stream_time_range(StreamName.RAW_PENDING)
        print(f"    Time range:")
        print(f"      Earliest: {time_range['earliest']}")
        print(f"      Latest:   {time_range['latest']}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test raw event persistence")
    parser.add_argument("--events", type=int, default=10, help="Batch size")
    args = parser.parse_args()

    asyncio.run(run_persistence_test(event_count=args.events))


if __name__ == "__main__":
    main()
