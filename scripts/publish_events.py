"""Event publishing CLI — publishes fake events to Redis Streams.

Connects to Redis and publishes events into the pipeline.

Usage:
    python -m scripts.publish_events --count 10
    python -m scripts.publish_events --count 50 --stream raw.pending
    python -m scripts.publish_events --count 5 --fail-rate 0.3
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.logging import setup_logging
from app.infrastructure.redis.streams import StreamsManager
from app.infrastructure.redis.producer import EventProducer
from app.core.domain.stream_names import StreamName
from scripts.fake_events import generate_fake_events


async def publish(
    count: int,
    stream: str,
    fail_rate: float,
) -> None:
    """Publish fake events to a Redis stream."""
    import structlog
    from redis.asyncio import Redis

    logger = structlog.get_logger("publish_cli")
    setup_logging(log_level="INFO", json_output=False)

    # Connect to Redis (streams DB)
    redis_url = os.getenv("REDIS_STREAMS_URL", "redis://localhost:6379/1")
    redis = Redis.from_url(redis_url, decode_responses=True)

    try:
        await redis.ping()
        logger.info("redis.connected", url=redis_url)
    except Exception as e:
        logger.error("redis.connection_failed", error=str(e))
        return

    streams = StreamsManager(redis)
    producer = EventProducer(streams)

    # Ensure consumer group exists
    await streams.ensure_groups()

    # Generate fake events
    fake_events = generate_fake_events(
        count=count,
        include_failures=fail_rate > 0,
        failure_rate=fail_rate,
    )

    logger.info(
        "publishing.start",
        count=len(fake_events),
        stream=stream,
    )

    published = 0
    for i, event_data in enumerate(fake_events, 1):
        try:
            redis_id = await producer.publish(
                stream=stream,
                event_type="raw.received",
                payload=event_data,
                metadata={"source": "fake_generator", "batch_index": i},
            )
            published += 1

            status_icon = "OK" if event_data["status"] == "success" else "FAIL"
            print(
                f"  [{i:>3}/{count}] {status_icon:>4} "
                f"published to {stream}  "
                f"redis_id={redis_id}  "
                f"sig={event_data['signature'][:16]}..."
            )

        except Exception as e:
            logger.error("publish.failed", index=i, error=str(e))

    logger.info("publishing.done", published=published, total=count)

    # Show stream stats
    info = await streams.stream_info(stream)
    print(f"\nStream {stream}: {info['length']} total entries")

    await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish fake events to Redis Streams")
    parser.add_argument("--count", type=int, default=10, help="Number of events")
    parser.add_argument(
        "--stream",
        type=str,
        default=StreamName.RAW_PENDING,
        help=f"Target stream (default: {StreamName.RAW_PENDING})",
    )
    parser.add_argument("--fail-rate", type=float, default=0.0, help="Failure rate (0-1)")
    args = parser.parse_args()

    asyncio.run(publish(
        count=args.count,
        stream=args.stream,
        fail_rate=args.fail_rate,
    ))


if __name__ == "__main__":
    main()
