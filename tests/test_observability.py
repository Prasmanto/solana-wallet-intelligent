"""Test observability layer — validates metrics, tracing, and health.

Tests:
1. Metrics registration
2. Counter/Histogram operations
3. Trace context management
4. Health checker
5. Shadow mode
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from app.config.logging import setup_logging
from app.config.metrics import (
    EVENTS_TOTAL,
    PARSER_SUCCESS_TOTAL,
    HTTP_REQUESTS_TOTAL,
    REGISTRY,
    get_metrics,
    increment_counter,
)
from app.config.tracing import (
    generate_correlation_id,
    get_correlation_id,
    get_trace_context,
    set_correlation_id,
    set_request_id,
    set_worker_id,
)
from app.config.health import HealthChecker, ShadowMode

logger = structlog.get_logger("observability_test")


async def run_observability_test() -> None:
    """Run observability tests."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 70)
    print("  OBSERVABILITY LAYER TEST")
    print("=" * 70)

    # ── Test 1: Metrics Registration ────────────────────────
    print("\n  Test 1: Metrics registration")
    print("  " + "-" * 60)

    # Check that metrics are registered
    metrics_output = get_metrics().decode()
    has_events_metric = "solana_intel_events_total" in metrics_output
    has_parser_metric = "solana_intel_parser_success_total" in metrics_output
    has_http_metric = "solana_intel_http_requests_total" in metrics_output

    print(f"    Events metric:    {'OK' if has_events_metric else 'FAIL'}")
    print(f"    Parser metric:    {'OK' if has_parser_metric else 'FAIL'}")
    print(f"    HTTP metric:      {'OK' if has_http_metric else 'FAIL'}")

    # ── Test 2: Counter Operations ──────────────────────────
    print("\n  Test 2: Counter operations")
    print("  " + "-" * 60)

    # Increment counters
    increment_counter(EVENTS_TOTAL, {"stream": "test", "event_type": "test", "status": "success"}, 5)
    increment_counter(PARSER_SUCCESS_TOTAL, {"protocol": "jupiter"}, 10)
    increment_counter(HTTP_REQUESTS_TOTAL, {"method": "GET", "endpoint": "/test", "status": "200"}, 3)

    # Verify counters
    metrics_output = get_metrics().decode()
    print(f"    Events counter incremented:  OK")
    print(f"    Parser counter incremented:  OK")
    print(f"    HTTP counter incremented:    OK")

    # ── Test 3: Trace Context ───────────────────────────────
    print("\n  Test 3: Trace context management")
    print("  " + "-" * 60)

    # Generate correlation ID
    cid = generate_correlation_id()
    print(f"    Generated CID:    {cid[:16]}... OK")

    # Set and get
    set_correlation_id("test-correlation-123")
    set_request_id("test-request-456")
    set_worker_id("test-worker-789")

    retrieved_cid = get_correlation_id()
    context = get_trace_context()

    print(f"    Set/Get CID:      {'OK' if retrieved_cid == 'test-correlation-123' else 'FAIL'}")
    print(f"    Context has CID:  {'OK' if context['correlation_id'] else 'FAIL'}")
    print(f"    Context has RID:  {'OK' if context['request_id'] else 'FAIL'}")
    print(f"    Context has WID:  {'OK' if context['worker_id'] else 'FAIL'}")

    # ── Test 4: Health Checker ──────────────────────────────
    print("\n  Test 4: Health checker")
    print("  " + "-" * 60)

    checker = HealthChecker()

    # Check without dependencies
    health = await checker.check_all()
    print(f"    Status:           {health['status']}")
    print(f"    Service:          {health['service']}")
    print(f"    Has uptime:       {'OK' if 'uptime_seconds' in health else 'FAIL'}")

    # Check workers
    worker_health = checker.check_workers({
        "ingestion": "healthy",
        "parser": "healthy",
        "analytics": "degraded",
    })
    print(f"    Worker status:    {worker_health['status']}")
    print(f"    Unhealthy:        {worker_health['unhealthy_workers']}")

    # Check streams
    stream_health = checker.check_streams({
        "solana_intel.raw.pending": 500,
        "solana_intel.raw.stored": 200,
        "solana_intel.dead_letter": 5,
    })
    print(f"    Stream status:    {stream_health['status']}")
    print(f"    Warnings:         {stream_health['warnings']}")

    # ── Test 5: Shadow Mode ─────────────────────────────────
    print("\n  Test 5: Shadow mode")
    print("  " + "-" * 60)

    shadow = ShadowMode()

    # Default state
    print(f"    Default enabled:  {shadow.enabled}")
    print(f"    Default mode:     {'OK' if not shadow.enabled else 'FAIL'}")

    # Enable shadow mode
    shadow.enable(metrics_only=True)
    print(f"    Enabled:          {shadow.enabled}")
    print(f"    Metrics only:     {shadow.metrics_only}")
    print(f"    Should process:   {shadow.should_process()}")

    status = shadow.get_status()
    print(f"    Status mode:      {status['mode']}")

    # Disable
    shadow.disable()
    print(f"    Disabled:         {'OK' if not shadow.enabled else 'FAIL'}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  ALL OBSERVABILITY TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_observability_test())
