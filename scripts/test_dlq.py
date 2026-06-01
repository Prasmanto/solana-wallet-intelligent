"""Dead-letter queue test — verifies DLQ routing after max retries.

Publishes events that fail every time, causing them to be dead-lettered
after exhausting max_retries.

Usage:
    python -m scripts.test_dlq --events 5
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from redis.asyncio import Redis

from app.config.logging import setup_logging
from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager
from app.workers.base import ConsumerWorker
from scripts.fake_events import generate_fake_events

logger = structlog.get_logger("dlq_test")


class AlwaysFailWorker(ConsumerWorker):
    """A worker that always fails — forces dead-lettering."""

    stream = StreamName.RAW_PENDING
    group = "dlq_test_group"
    consumer = "failing-worker-1"
    concurrency = 1
    block_ms = 2000

    async def process(self, envelope: EventEnvelope) -> None:
        raise RuntimeError("Simulated permanent failure — this event cannot be processed")


async def run_dlq_test(event_count: int) -> None:
    """Run the DLQ simulation."""
    setup_logging(log_level="WARNING", json_output=False)

    redis_url = os.getenv("REDIS_STREAMS_URL", "redis://localhost:6379/1")
    redis = Redis.from_url(redis_url, decode_responses=True)

    try:
        await redis.ping()
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis: {e}")
        return

    streams = StreamsManager(redis)
    producer = EventProducer(streams)

    # Clean up previous test state
    try:
        await redis.delete(StreamName.RAW_PENDING)
        await redis.delete(StreamName.DEAD_LETTER)
    except Exception:
        pass

    await streams.ensure_groups()

    # Create test-specific consumer group
    try:
        await redis.xgroup_create(StreamName.RAW_PENDING, "dlq_test_group", id="0", mkstream=True)
    except Exception:
        pass  # BUSYGROUP means it already exists

    # Create always-fail worker with max_retries=2
    worker = AlwaysFailWorker(streams=streams, producer=producer)
    max_retries = 2

    # Publish events
    print(f"\nPublishing {event_count} events (max_retries={max_retries})...")
    print("Events will fail on every attempt and be dead-lettered.\n")

    for event_data in generate_fake_events(count=event_count):
        await producer.publish(
            stream=StreamName.RAW_PENDING,
            event_type="raw.received",
            payload=event_data,
            max_retries=max_retries,
            metadata={"test": "dlq"},
        )

    # Start worker
    print("Starting always-fail worker...\n")
    worker_task = asyncio.create_task(worker.run())

    # Wait for DLQ to populate
    max_wait = 20
    start = time.time()
    dlq_count = 0

    while time.time() - start < max_wait:
        try:
            dlq_info = await redis.xinfo_stream(StreamName.DEAD_LETTER)
            dlq_count = dlq_info.get("length", 0)
        except Exception:
            dlq_count = 0

        if dlq_count >= event_count:
            break

        await asyncio.sleep(0.5)

    # Shutdown
    await worker.shutdown()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    # Inspect DLQ
    print("\n" + "=" * 70)
    print("  DEAD-LETTER QUEUE TEST REPORT")
    print("=" * 70)
    print(f"  Events published:    {event_count}")
    print(f"  Max retries:         {max_retries}")
    print(f"  DLQ entries:         {dlq_count}")
    print("-" * 70)

    if dlq_count > 0:
        print("\n  DLQ Messages:")
        try:
            # Read DLQ entries
            dlq_entries = await redis.xrange(
                StreamName.DEAD_LETTER,
                count=dlq_count,
            )
            for redis_id, fields in dlq_entries:
                print(f"\n  Stream ID: {redis_id}")
                print(f"    Event ID:        {fields.get('event_id', '?')[:16]}...")
                print(f"    Event Type:      {fields.get('event_type', '?')}")
                print(f"    Retry Count:     {fields.get('retry_count', '?')}")
                print(f"    Original Stream: {fields.get('dlq_original_stream', '?')}")
                print(f"    DLQ Reason:      {fields.get('dlq_reason', '?')[:50]}...")
        except Exception as e:
            print(f"    Error reading DLQ: {e}")

    print("\n" + "=" * 70)
    print("  DLQ routing verified" if dlq_count >= event_count else "  DLQ routing incomplete")
    print("=" * 70)

    await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dead-letter queue test")
    parser.add_argument("--events", type=int, default=3, help="Number of events")
    args = parser.parse_args()

    asyncio.run(run_dlq_test(event_count=args.events))


if __name__ == "__main__":
    main()
