"""Stream inspector — utility to inspect Redis Streams state.

Shows stream lengths, consumer groups, pending messages, and DLQ contents.

Usage:
    python -m scripts.inspect_streams
    python -m scripts.inspect_streams --stream solana_intel.raw.pending
    python -m scripts.inspect_streams --dlq
    python -m scripts.inspect_streams --reset
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.logging import setup_logging
from app.core.domain.stream_names import StreamName
from app.infrastructure.redis.streams import StreamsManager

setup_logging(log_level="WARNING", json_output=False)


async def inspect_all(redis_streams_url: str) -> None:
    """Inspect all streams."""
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_streams_url, decode_responses=True)
    streams = StreamsManager(redis)

    print("\n" + "=" * 70)
    print("  REDIS STREAMS INSPECTOR")
    print("=" * 70)

    # Stream info
    print("\n  Stream Lengths:")
    print("  " + "-" * 50)
    for stream in StreamName.ALL:
        info = await streams.stream_info(stream)
        length = info.get("length", 0)
        bar = "#" * min(length, 40)
        print(f"    {stream:<35} {length:>6}  {bar}")

    # DLQ
    try:
        dlq_info = await redis.xinfo_stream(StreamName.DEAD_LETTER)
        dlq_length = dlq_info.get("length", 0)
    except Exception:
        dlq_length = 0

    dlq_bar = "#" * min(dlq_length, 40)
    print(f"    {'dead_letter':<35} {dlq_length:>6}  {dlq_bar}")

    # Consumer groups
    print("\n  Consumer Groups:")
    print("  " + "-" * 50)
    for stream in StreamName.ALL:
        try:
            groups = await redis.xinfo_groups(stream)
            for g in groups:
                name = g.get("name", "?")
                pending = g.get("pending", 0)
                consumers = g.get("consumers", 0)
                print(f"    {stream:<35} {name:<20} pending={pending}  consumers={consumers}")
        except Exception:
            print(f"    {stream:<35} (no groups)")

    print("\n" + "=" * 70)


async def inspect_stream(redis_streams_url: str, stream: str) -> None:
    """Inspect a single stream in detail."""
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_streams_url, decode_responses=True)
    streams = StreamsManager(redis)

    print(f"\n  Stream: {stream}")
    print("=" * 70)

    info = await streams.stream_info(stream)
    print(f"  Length: {info.get('length', 0)}")
    print(f"  First entry: {info.get('first_entry', 'N/A')}")
    print(f"  Last entry: {info.get('last_entry', 'N/A')}")

    # Consumer groups
    try:
        groups = await redis.xinfo_groups(stream)
        print(f"\n  Consumer Groups ({len(groups)}):")
        for g in groups:
            print(f"    - {g.get('name')}: pending={g.get('pending', 0)}, consumers={g.get('consumers', 0)}")
    except Exception:
        print("\n  No consumer groups")

    # Pending messages
    try:
        for g in groups:
            group_name = g.get("name")
            pending = await redis.xpending(stream, group_name)
            print(f"\n  Pending for {group_name}:")
            print(f"    Total: {pending.get('pending', 0)}")
            print(f"    Min idle: {pending.get('min-idle', 0)}ms")
    except Exception:
        pass

    print("=" * 70)


async def inspect_dlq(redis_streams_url: str, limit: int = 10) -> None:
    """Inspect dead-letter queue contents."""
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_streams_url, decode_responses=True)

    print("\n" + "=" * 70)
    print("  DEAD-LETTER QUEUE")
    print("=" * 70)

    try:
        dlq_info = await redis.xinfo_stream(StreamName.DEAD_LETTER)
        total = dlq_info.get("length", 0)
        print(f"  Total entries: {total}")
    except Exception:
        print("  No DLQ entries")
        return

    if total == 0:
        print("=" * 70)
        return

    entries = await redis.xrange(StreamName.DEAD_LETTER, count=limit)
    print(f"\n  Showing {min(limit, total)} entries:")
    print("  " + "-" * 60)

    for redis_id, fields in entries:
        print(f"\n  [{redis_id}]")
        print(f"    Event ID:      {fields.get('event_id', '?')[:20]}...")
        print(f"    Event Type:    {fields.get('event_type', '?')}")
        print(f"    Correlation:   {fields.get('correlation_id', '?')[:20]}...")
        print(f"    Retry Count:   {fields.get('retry_count', '?')} / {fields.get('max_retries', '?')}")
        print(f"    Original:      {fields.get('dlq_original_stream', '?')}")
        print(f"    Reason:        {fields.get('dlq_reason', '?')[:60]}")

    print("\n" + "=" * 70)


async def reset_streams(redis_streams_url: str) -> None:
    """Delete all streams and consumer groups (use with caution)."""
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_streams_url, decode_responses=True)
    streams = StreamsManager(redis)

    print("\n  Resetting all streams...")

    await streams.destroy_groups()

    for stream in StreamName.ALL + [StreamName.DEAD_LETTER]:
        try:
            await redis.delete(stream)
            print(f"    Deleted: {stream}")
        except Exception:
            pass

    print("\n  All streams reset.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Redis Streams inspector")
    parser.add_argument("--stream", type=str, help="Inspect a specific stream")
    parser.add_argument("--dlq", action="store_true", help="Inspect dead-letter queue")
    parser.add_argument("--dlq-limit", type=int, default=10, help="DLQ entries to show")
    parser.add_argument("--reset", action="store_true", help="Delete all streams (dangerous!)")
    args = parser.parse_args()

    redis_streams_url = os.getenv("REDIS_STREAMS_URL", "redis://localhost:6379/1")

    if args.reset:
        confirm = input("Type 'yes' to confirm reset: ")
        if confirm.lower() == "yes":
            asyncio.run(reset_streams(redis_streams_url))
        else:
            print("Aborted.")
    elif args.dlq:
        asyncio.run(inspect_dlq(redis_streams_url, limit=args.dlq_limit))
    elif args.stream:
        asyncio.run(inspect_stream(redis_streams_url, args.stream))
    else:
        asyncio.run(inspect_all(redis_streams_url))


if __name__ == "__main__":
    main()
