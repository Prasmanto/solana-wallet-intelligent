"""Retry simulation — tests the retry mechanism with a failing worker.

Publishes events that will cause the worker to fail 3 times before succeeding
(or be dead-lettered after max retries).

Usage:
    python -m scripts.test_retry --events 5
"""

from __future__ import annotations

import asyncio
import argparse
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

logger = structlog.get_logger("retry_test")

# Track which events have been retried
_retry_counts: dict[str, int] = {}


class FlakyWorker(ConsumerWorker):
    """A worker that fails the first N attempts per event."""

    stream = StreamName.RAW_PENDING
    group = "retry_test_group"
    consumer = "flaky-worker-1"
    concurrency = 1
    block_ms = 2000
    fail_until_attempt = 2  # Fail first 2 attempts, succeed on 3rd

    async def process(self, envelope: EventEnvelope) -> None:
        event_id = envelope.event_id
        _retry_counts[event_id] = _retry_counts.get(event_id, 0) + 1
        attempt = _retry_counts[event_id]

        print(f"  Attempt {attempt} for event {event_id[:8]}...")

        if attempt < self.fail_until_attempt:
            raise ValueError(f"Simulated failure (attempt {attempt}/{self.fail_until_attempt})")

        print(f"  [OK] Event {event_id[:8]}... succeeded on attempt {attempt}")
        # Simulate some work
        await asyncio.sleep(0.01)


async def run_retry_test(event_count: int) -> None:
    """Run the retry simulation."""
    setup_logging(log_level="INFO", json_output=False)

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
    except Exception:
        pass

    await streams.ensure_groups()

    # Create test-specific consumer group
    try:
        await redis.xgroup_create(StreamName.RAW_PENDING, "retry_test_group", id="0", mkstream=True)
    except Exception:
        pass  # BUSYGROUP means it already exists

    # Create flaky worker
    worker = FlakyWorker(streams=streams, producer=producer)

    # Publish events
    print(f"\nPublishing {event_count} events (each will fail {worker.fail_until_attempt - 1} times)...\n")
    for event_data in generate_fake_events(count=event_count):
        await producer.publish(
            stream=StreamName.RAW_PENDING,
            event_type="raw.received",
            payload=event_data,
            metadata={"test": "retry"},
        )

    # Start worker
    print("Starting flaky worker...\n")
    worker_task = asyncio.create_task(worker.run())

    # Wait for all events to be processed
    max_wait = 30
    start = time.time()
    while time.time() - start < max_wait:
        pending = await streams.pending_info(StreamName.RAW_PENDING, "retry_test_group")
        pending_count = pending.get("pending", 0)

        # Check if there are any unacked messages
        try:
            info = await redis.xinfo_stream(StreamName.RAW_PENDING)
            total = info.get("length", 0)
        except Exception:
            total = 0

        if total == 0 and pending_count == 0:
            break

        await asyncio.sleep(0.5)

    # Shutdown
    await worker.shutdown()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    # Report
    print("\n" + "=" * 60)
    print("  RETRY TEST REPORT")
    print("=" * 60)
    print(f"  Events published:    {event_count}")
    print(f"  Total attempts:      {sum(_retry_counts.values())}")
    print(f"  Avg attempts/event:  {sum(_retry_counts.values()) / max(len(_retry_counts), 1):.1f}")
    print("-" * 60)
    for event_id, count in _retry_counts.items():
        status = "succeeded" if count >= 2 else "still failing"
        print(f"  {event_id[:12]}...  {count} attempts  {status}")
    print("=" * 60)

    await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry simulation test")
    parser.add_argument("--events", type=int, default=3, help="Number of events")
    args = parser.parse_args()

    asyncio.run(run_retry_test(event_count=args.events))


if __name__ == "__main__":
    main()
