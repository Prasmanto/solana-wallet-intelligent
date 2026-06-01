"""Metrics configuration — Prometheus integration.

Provides:
- Metrics registry and collector
- Custom metric definitions
- Middleware for HTTP metrics
- Worker metrics collection

Uses prometheus_client for metrics exposition.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

import structlog
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

logger = structlog.get_logger(__name__)

# ── Metrics Registry ────────────────────────────────────────

REGISTRY = CollectorRegistry()

# ── Application Info ────────────────────────────────────────

APP_INFO = Info(
    "solana_intel_app",
    "Application information",
    registry=REGISTRY,
)

# ── Event Pipeline Metrics ──────────────────────────────────

EVENTS_TOTAL = Counter(
    "solana_intel_events_total",
    "Total events processed",
    ["stream", "event_type", "status"],
    registry=REGISTRY,
)

EVENT_PROCESSING_DURATION = Histogram(
    "solana_intel_event_processing_seconds",
    "Event processing duration",
    ["stream", "worker"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

EVENT_RETRY_TOTAL = Counter(
    "solana_intel_event_retries_total",
    "Total event retries",
    ["stream", "worker"],
    registry=REGISTRY,
)

EVENT_DLQ_TOTAL = Counter(
    "solana_intel_event_dlq_total",
    "Total events sent to dead letter queue",
    ["stream", "worker", "reason"],
    registry=REGISTRY,
)

# ── Stream Depth Metrics ────────────────────────────────────

STREAM_DEPTH = Gauge(
    "solana_intel_stream_depth",
    "Current stream depth (number of entries)",
    ["stream"],
    registry=REGISTRY,
)

STREAM_CONSUMER_LAG = Gauge(
    "solana_intel_consumer_lag",
    "Consumer group lag (pending messages)",
    ["stream", "group"],
    registry=REGISTRY,
)

# ── Worker Metrics ──────────────────────────────────────────

WORKER_UPTIME = Gauge(
    "solana_intel_worker_uptime_seconds",
    "Worker uptime in seconds",
    ["worker", "stream"],
    registry=REGISTRY,
)

WORKER_CONCURRENCY = Gauge(
    "solana_intel_worker_concurrency",
    "Current worker concurrency (active tasks)",
    ["worker", "stream"],
    registry=REGISTRY,
)

WORKER_ERROR_TOTAL = Counter(
    "solana_intel_worker_errors_total",
    "Total worker errors",
    ["worker", "stream", "error_type"],
    registry=REGISTRY,
)

# ── Parser Metrics ──────────────────────────────────────────

PARSER_SUCCESS_TOTAL = Counter(
    "solana_intel_parser_success_total",
    "Total successful parses",
    ["protocol"],
    registry=REGISTRY,
)

PARSER_FAILURE_TOTAL = Counter(
    "solana_intel_parser_failure_total",
    "Total parse failures",
    ["error_code"],
    registry=REGISTRY,
)

PARSER_DURATION = Histogram(
    "solana_intel_parser_duration_seconds",
    "Parse duration",
    ["protocol"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
    registry=REGISTRY,
)

# ── Pricing Metrics ─────────────────────────────────────────

PRICING_FRESHNESS = Gauge(
    "solana_intel_pricing_freshness_seconds",
    "Age of most recent price in seconds",
    ["token"],
    registry=REGISTRY,
)

PRICING_FETCH_TOTAL = Counter(
    "solana_intel_pricing_fetch_total",
    "Total price fetches",
    ["source", "status"],
    registry=REGISTRY,
)

PRICING_CACHE_HIT_TOTAL = Counter(
    "solana_intel_pricing_cache_hits_total",
    "Total cache hits",
    ["token"],
    registry=REGISTRY,
)

# ── Database Metrics ────────────────────────────────────────

DB_WRITE_DURATION = Histogram(
    "solana_intel_db_write_seconds",
    "Database write operation duration",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=REGISTRY,
)

DB_READ_DURATION = Histogram(
    "solana_intel_db_read_seconds",
    "Database read operation duration",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
    registry=REGISTRY,
)

DB_POOL_SIZE = Gauge(
    "solana_intel_db_pool_size",
    "Database connection pool size",
    ["state"],
    registry=REGISTRY,
)

# ── Redis Metrics ───────────────────────────────────────────

REDIS_OPERATION_DURATION = Histogram(
    "solana_intel_redis_operation_seconds",
    "Redis operation duration",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1],
    registry=REGISTRY,
)

# ── Position Metrics ────────────────────────────────────────

POSITION_UPDATES_TOTAL = Counter(
    "solana_intel_position_updates_total",
    "Total position updates",
    ["wallet", "token", "direction"],
    registry=REGISTRY,
)

POSITION_PNL = Gauge(
    "solana_intel_position_pnl",
    "Current position PnL",
    ["wallet", "token", "type"],
    registry=REGISTRY,
)

# ── HTTP Metrics ────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "solana_intel_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "solana_intel_http_request_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)

# ── Helius Webhook Failover Metrics ─────────────────────────

HELIUS_CURRENT_KEY_INDEX = Gauge(
    "helius_current_key_index",
    "Current active API key index",
    registry=REGISTRY,
)

HELIUS_WEBHOOK_ACTIVE = Gauge(
    "helius_webhook_active",
    "Whether a webhook is currently active (1=yes, 0=no)",
    registry=REGISTRY,
)

HELIUS_FAILOVERS_TOTAL = Counter(
    "helius_webhook_failovers_total",
    "Total webhook failovers performed",
    ["from_provider", "to_provider", "reason"],
    registry=REGISTRY,
)

HELIUS_LAST_EVENT_AGE = Gauge(
    "helius_last_event_age_seconds",
    "Seconds since last webhook event was received",
    registry=REGISTRY,
)

HELIUS_KEYS_AVAILABLE = Gauge(
    "helius_keys_available",
    "Number of available (active, non-exhausted) API keys",
    registry=REGISTRY,
)

HELIUS_KEYS_EXHAUSTED = Gauge(
    "helius_keys_exhausted",
    "Number of exhausted API keys",
    registry=REGISTRY,
)


# ── Helper Functions ────────────────────────────────────────

def init_app_info(version: str, env: str, commit: str = "") -> None:
    """Initialize application info metric."""
    APP_INFO.info({
        "version": version,
        "env": env,
        "commit": commit,
    })


def get_metrics() -> bytes:
    """Get Prometheus metrics as bytes."""
    return generate_latest(REGISTRY)


@contextmanager
def track_duration(
    histogram: Histogram,
    labels: dict[str, str] | None = None,
) -> Generator[None, None, None]:
    """Context manager to track operation duration."""
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        if labels:
            histogram.labels(**labels).observe(duration)
        else:
            histogram.observe(duration)


def increment_counter(
    counter: Counter,
    labels: dict[str, str],
    value: int = 1,
) -> None:
    """Increment a counter with labels."""
    counter.labels(**labels).inc(value)
