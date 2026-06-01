"""Local market features — token-specific features per timeframe.

Computes token-specific features:
- local_liquidity_window (30s / 5m / 1h)
- local_velocity
- local_cluster_pressure
- local_anomaly_deviation

These are NOT identical to global features.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LocalMarketFeatures:
    """Token-specific local market features."""

    def compute_local_features(
        self,
        token: str,
        events: list[dict[str, Any]],
    ) -> dict[str, dict[str, float]]:
        """Compute local market features for a token.

        Returns features for 3 timeframes: 30s, 5m, 1h
        """
        features = {}

        # Short-term (30s)
        features["short_term"] = self._compute_window_features(events, 30)

        # Mid-term (5m)
        features["mid_term"] = self._compute_window_features(events, 300)

        # Long-term (1h)
        features["long_term"] = self._compute_window_features(events, 3600)

        return features

    def _compute_window_features(
        self,
        events: list[dict[str, Any]],
        window_seconds: int,
    ) -> dict[str, float]:
        """Compute features for a specific time window."""
        if not events:
            return self._empty_features()

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_seconds)

        window_events = [
            e for e in events
            if self._get_timestamp(e) >= cutoff
        ]

        if not window_events:
            return self._empty_features()

        # Compute features
        volume = sum(e.get("amount", 0) for e in window_events)
        tx_count = len(window_events)
        wallets = set(e.get("wallet", "") for e in window_events if e.get("wallet"))
        buys = sum(1 for e in window_events if e.get("event_type") == "BUY")

        # Liquidity: buy ratio
        liquidity = buys / tx_count if tx_count > 0 else 0.0

        # Velocity: events per second
        velocity = tx_count / window_seconds if window_seconds > 0 else 0.0

        # Cluster pressure: unique wallets / total events
        cluster_pressure = len(wallets) / tx_count if tx_count > 0 else 0.0

        # Anomaly deviation: volume compared to average
        avg_volume = volume / tx_count if tx_count > 0 else 0.0
        anomaly_deviation = min(1.0, avg_volume / 1000)  # Normalize

        return {
            "liquidity": min(1.0, liquidity),
            "velocity": min(1.0, velocity * 100),  # Scale to 0-1
            "cluster_pressure": min(1.0, cluster_pressure),
            "anomaly_deviation": anomaly_deviation,
            "volume": volume,
            "tx_count": tx_count,
            "wallet_count": len(wallets),
        }

    def _empty_features(self) -> dict[str, float]:
        """Return empty features."""
        return {
            "liquidity": 0.0,
            "velocity": 0.0,
            "cluster_pressure": 0.0,
            "anomaly_deviation": 0.0,
            "volume": 0.0,
            "tx_count": 0,
            "wallet_count": 0,
        }

    def _get_timestamp(self, event: dict[str, Any]) -> datetime:
        """Extract timestamp from event."""
        ts = event.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.now(timezone.utc)
