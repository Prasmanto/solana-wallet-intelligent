"""Full pipeline simulation — simulates the complete event flow.

Runs all 5 pipeline stages as concurrent workers:
  raw.pending → raw.stored → trade.normalized → trade.enriched → alert.triggered

Each stage transforms the event payload and chains to the next stream.

Usage:
    python -m scripts.simulate_pipeline --events 10 --duration 30
"""

from __future__ import annotations

import asyncio
import argparse
import os
import signal
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from redis.asyncio import Redis

from app.config.logging import setup_logging
from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.redis.manager import RedisManager
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager
from app.workers.base import ConsumerWorker
from scripts.fake_events import generate_fake_events

logger = structlog.get_logger("pipeline_sim")


# ── Simulated Workers ───────────────────────────────────────


class IngestionSim(ConsumerWorker):
    """Stage 1: raw.pending → raw.stored"""

    stream = StreamName.RAW_PENDING
    group = "sim_ingestion"
    consumer = "sim-ingestion-1"
    concurrency = 2
    block_ms = 2000

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload_dict

        # Simulate validation + DB storage
        await asyncio.sleep(0.01)

        # Transform: add validation metadata
        enriched = {
            **payload,
            "validated": True,
            "stored_at": time.time(),
        }

        # Chain to next stream
        await self._producer.publish_chain(
            stream=StreamName.RAW_STORED,
            event_type="raw.stored",
            payload=enriched,
            source_envelope=envelope,
            metadata={"stage": "ingestion", "worker": "sim"},
        )


class ParserSim(ConsumerWorker):
    """Stage 2: raw.stored → trade.normalized"""

    stream = StreamName.RAW_STORED
    group = "sim_parser"
    consumer = "sim-parser-1"
    concurrency = 2
    block_ms = 2000

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload_dict

        # Simulate parsing instructions
        await asyncio.sleep(0.01)

        # Transform: normalize to trade
        trade = {
            "trade_id": envelope.event_id,
            "signature": payload.get("signature"),
            "wallet": payload.get("from_wallet"),
            "counterparty": payload.get("to_wallet"),
            "token": "SOL" if payload.get("mint") is None else payload.get("mint"),
            "amount": payload.get("amount_sol", 0),
            "type": payload.get("tx_type"),
            "program": payload.get("program_id"),
            "normalized_at": time.time(),
        }

        await self._producer.publish_chain(
            stream=StreamName.TRADE_NORMALIZED,
            event_type="trade.normalized",
            payload=trade,
            source_envelope=envelope,
            metadata={"stage": "parser", "worker": "sim"},
        )


class AnalyticsSim(ConsumerWorker):
    """Stage 3: trade.normalized → trade.enriched"""

    stream = StreamName.TRADE_NORMALIZED
    group = "sim_analytics"
    consumer = "sim-analytics-1"
    concurrency = 2
    block_ms = 2000

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload_dict

        # Simulate analytics computation
        await asyncio.sleep(0.01)

        # Transform: add risk score + aggregates
        enriched = {
            **payload,
            "risk_score": 0.3 if payload.get("amount", 0) < 100 else 0.7,
            "wallet_label": "defi_trader",
            "volume_24h": payload.get("amount", 0) * 1.2,
            "analyzed_at": time.time(),
        }

        await self._producer.publish_chain(
            stream=StreamName.TRADE_ENRICHED,
            event_type="trade.enriched",
            payload=enriched,
            source_envelope=envelope,
            metadata={"stage": "analytics", "worker": "sim"},
        )


class AlertSim(ConsumerWorker):
    """Stage 4: trade.enriched → alert.triggered"""

    stream = StreamName.TRADE_ENRICHED
    group = "sim_alert"
    consumer = "sim-alert-1"
    concurrency = 2
    block_ms = 2000

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload_dict

        # Simulate rule evaluation
        await asyncio.sleep(0.01)

        risk_score = payload.get("risk_score", 0)
        amount = payload.get("amount", 0)

        alerts = []
        if risk_score > 0.5:
            alerts.append("high_risk_wallet")
        if amount > 1000:
            alerts.append("large_transaction")
        if payload.get("type") == "swap":
            alerts.append("defi_activity")

        if alerts:
            await self._producer.publish_chain(
                stream=StreamName.ALERT_TRIGGERED,
                event_type="alert.triggered",
                payload={
                    "alerts": alerts,
                    "trade": payload,
                    "triggered_at": time.time(),
                },
                source_envelope=envelope,
                metadata={"stage": "alert", "worker": "sim"},
            )


# ── Stats Collector ─────────────────────────────────────────


class PipelineStats:
    """Collects and displays pipeline metrics."""

    def __init__(self) -> None:
        self.events_processed: dict[str, int] = {}
        self.events_per_second: float = 0.0
        self._start_time: float = 0.0
        self._total_events: int = 0

    def start(self) -> None:
        self._start_time = time.monotonic()

    def record(self, stage: str) -> None:
        self.events_processed[stage] = self.events_processed.get(stage, 0) + 1
        self._total_events += 1

    def report(self) -> None:
        elapsed = time.monotonic() - self._start_time
        if elapsed > 0:
            self.events_per_second = self._total_events / elapsed

        print("\n" + "=" * 60)
        print("  PIPELINE SIMULATION REPORT")
        print("=" * 60)
        print(f"  Duration:        {elapsed:.1f}s")
        print(f"  Total events:    {self._total_events}")
        print(f"  Events/sec:      {self.events_per_second:.1f}")
        print("-" * 60)
        for stage, count in self.events_processed.items():
            print(f"  {stage:<30} {count:>6}")
        print("=" * 60)


# ── Main Simulation ─────────────────────────────────────────


async def run_simulation(events: int, duration: int) -> None:
    """Run the full pipeline simulation."""
    setup_logging(log_level="WARNING", json_output=False)

    redis_url = os.getenv("REDIS_STREAMS_URL", "redis://localhost:6379/1")
    redis = Redis.from_url(redis_url, decode_responses=True)

    try:
        await redis.ping()
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis at {redis_url}: {e}")
        return

    streams = StreamsManager(redis)
    producer = EventProducer(streams)

    # Ensure all consumer groups (both standard and simulation-specific)
    await streams.ensure_groups()

    # Create simulation-specific consumer groups
    sim_groups = [
        (StreamName.RAW_PENDING, "sim_ingestion"),
        (StreamName.RAW_STORED, "sim_parser"),
        (StreamName.TRADE_NORMALIZED, "sim_analytics"),
        (StreamName.TRADE_ENRICHED, "sim_alert"),
    ]
    for stream_name, group_name in sim_groups:
        try:
            await redis.xgroup_create(stream_name, group_name, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                print(f"Warning: Could not create group {group_name}: {e}")

    # Create workers
    workers = [
        IngestionSim(streams=streams, producer=producer),
        ParserSim(streams=streams, producer=producer),
        AnalyticsSim(streams=streams, producer=producer),
        AlertSim(streams=streams, producer=producer),
    ]

    stats = PipelineStats()

    # Publish initial events
    print(f"\nPublishing {events} events to {StreamName.RAW_PENDING}...")
    for event_data in generate_fake_events(count=events):
        await producer.publish(
            stream=StreamName.RAW_PENDING,
            event_type="raw.received",
            payload=event_data,
            metadata={"source": "pipeline_sim"},
        )
    print(f"Events published. Starting workers...\n")

    # Start workers
    tasks = [asyncio.create_task(w.run()) for w in workers]
    stats.start()

    # Run for duration or until interrupted
    shutdown = asyncio.Event()

    def handle_signal():
        shutdown.set()

    # Signal handling (Windows-compatible)
    loop = asyncio.get_running_loop()
    if os.name != "nt":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)
    else:
        # On Windows, Ctrl+C raises KeyboardInterrupt
        pass

    # Monitor in background
    async def monitor():
        while not shutdown.is_set():
            await asyncio.sleep(2)
            # Check stream lengths
            for stream in StreamName.ALL:
                try:
                    info = await streams.stream_info(stream)
                    length = info.get("length", 0)
                    if length > 0:
                        print(f"  [{time.strftime('%H:%M:%S')}] {stream}: {length} entries")
                except Exception:
                    pass

    monitor_task = asyncio.create_task(monitor())

    try:
        await asyncio.wait_for(shutdown.wait(), timeout=duration)
    except asyncio.TimeoutError:
        print(f"\nSimulation completed after {duration}s")
    except KeyboardInterrupt:
        print("\nInterrupted by user")

    # Shutdown
    for worker in workers:
        await worker.shutdown()

    monitor_task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Final stats
    # Count events in each stream
    for stream in StreamName.ALL:
        try:
            info = await streams.stream_info(stream)
            stats.events_processed[stream] = info.get("length", 0)
        except Exception:
            pass

    stats.report()
    await redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Full pipeline simulation")
    parser.add_argument("--events", type=int, default=10, help="Number of events")
    parser.add_argument("--duration", type=int, default=30, help="Max duration (seconds)")
    args = parser.parse_args()

    asyncio.run(run_simulation(events=args.events, duration=args.duration))


if __name__ == "__main__":
    main()
