"""Stream naming conventions.

All Redis Streams are namespaced under a common prefix to avoid
collisions with other Redis usage in the same instance.

Pattern: {prefix}.{domain}.{action}

Consumer groups follow: {stream_name}.{consumer_group}
"""

from __future__ import annotations

# Global prefix for all streams (configurable via env)
STREAM_PREFIX = "solana_intel"


class StreamName:
    """Canonical stream names and consumer group definitions.

    Usage:
        from app.core.domain.stream_names import Stream

        stream = Stream.RAW_PENDING       # "solana_intel.raw.pending"
        group  = Stream.group(stream)     # "solana_intel.raw.pending.ingestion"
    """

    # ── Pipeline Streams ─────────────────────────────────────

    # Stage 1: Raw events from Solana (unvalidated)
    RAW_PENDING = f"{STREAM_PREFIX}.raw.pending"

    # Stage 2: Validated raw events (stored in DB)
    RAW_STORED = f"{STREAM_PREFIX}.raw.stored"

    # Stage 3: Normalized trades
    TRADE_NORMALIZED = f"{STREAM_PREFIX}.trade.normalized"

    # Stage 4: Enriched trades (analytics applied)
    TRADE_ENRICHED = f"{STREAM_PREFIX}.trade.enriched"

    # Stage 5: Alerts triggered
    ALERT_TRIGGERED = f"{STREAM_PREFIX}.alert.triggered"

    # ── Intelligence Streams ──────────────────────────────────

    # Aggregated features (from aggregation worker)
    AGGREGATED_FEATURES = f"{STREAM_PREFIX}.aggregated.features"

    # Predictions (from prediction worker)
    PREDICTIONS = f"{STREAM_PREFIX}.predictions"

    # Rankings (from ranking worker)
    RANKINGS = f"{STREAM_PREFIX}.rankings"

    # Paper trading signals
    PAPER_TRADING = f"{STREAM_PREFIX}.paper.trading"

    # ── Dead Letter Queue ────────────────────────────────────

    DEAD_LETTER = f"{STREAM_PREFIX}.dead_letter"

    # ── All streams (for iteration) ──────────────────────────

    ALL = [
        RAW_PENDING,
        RAW_STORED,
        TRADE_NORMALIZED,
        TRADE_ENRICHED,
        ALERT_TRIGGERED,
        AGGREGATED_FEATURES,
        PREDICTIONS,
        RANKINGS,
        PAPER_TRADING,
    ]

    # ── Consumer Group Definitions ───────────────────────────

    # Maps stream → list of (group_name, consumer_name) pairs
    # Each worker type consumes from specific streams with its own group
    GROUPS: dict[str, list[tuple[str, str]]] = {
        RAW_PENDING: [
            ("ingestion", "ingestion-worker-1"),
        ],
        RAW_STORED: [
            ("parser", "parser-worker-1"),
        ],
        TRADE_NORMALIZED: [
            ("analytics", "analytics-worker-1"),
        ],
        TRADE_ENRICHED: [
            ("aggregation", "aggregation-worker-1"),
            ("alert", "alert-worker-1"),
        ],
        ALERT_TRIGGERED: [
            ("dispatch", "dispatch-worker-1"),
        ],
        AGGREGATED_FEATURES: [
            ("prediction", "prediction-worker-1"),
        ],
        PREDICTIONS: [
            ("ranking", "ranking-worker-1"),
        ],
        RANKINGS: [
            ("paper_trading", "paper-trading-worker-1"),
        ],
        PAPER_TRADING: [],
        DEAD_LETTER: [
            ("dlq-processor", "dlq-worker-1"),
        ],
    }

    @classmethod
    def group(cls, stream: str) -> str:
        """Get the consumer group name for a stream."""
        groups = cls.GROUPS.get(stream, [])
        if groups:
            return groups[0][0]
        # Fallback: derive from stream name
        return f"{stream}.default"

    @classmethod
    def consumer(cls, stream: str) -> str:
        """Get the default consumer name for a stream."""
        groups = cls.GROUPS.get(stream, [])
        if groups:
            return groups[0][1]
        return f"{stream}.consumer-1"

    @classmethod
    def next_stream(cls, current: str) -> str | None:
        """Get the next stream in the pipeline for chain linking."""
        pipeline = [
            cls.RAW_PENDING,
            cls.RAW_STORED,
            cls.TRADE_NORMALIZED,
            cls.TRADE_ENRICHED,
            cls.AGGREGATED_FEATURES,
            cls.PREDICTIONS,
            cls.RANKINGS,
            cls.PAPER_TRADING,
        ]
        try:
            idx = pipeline.index(current)
            if idx + 1 < len(pipeline):
                return pipeline[idx + 1]
        except ValueError:
            pass
        return None
