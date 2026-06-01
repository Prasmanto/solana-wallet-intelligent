"""Persistent feature store — computes and stores wallet features per time window.

Time windows:
- 5m: short-term activity
- 1h: medium-term activity
- 24h: long-term activity

Features stored:
- volume
- tx_frequency
- avg_interval
- token_diversity
- buy_sell_ratio
- interaction_score
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Time windows in seconds
TIME_WINDOWS = {
    "5m": 300,
    "1h": 3600,
    "24h": 86400,
}


class PersistentFeatureStore:
    """Persistent feature store with time-windowed aggregation."""

    def __init__(self, repo: Any) -> None:
        self._repo = repo

    async def extract_and_store(
        self,
        wallet: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract features and store for each time window."""
        features = {}

        for window_name, window_seconds in TIME_WINDOWS.items():
            window_events = self._filter_by_time(events, window_seconds)
            window_features = self._extract_features(wallet, window_events)

            # Persist to DB
            try:
                await self._repo.upsert_feature(
                    wallet_address=wallet,
                    time_window=window_name,
                    features=window_features,
                )
            except Exception as e:
                logger.error(
                    "features.persist_error",
                    wallet=wallet[:16],
                    window=window_name,
                    error=str(e),
                    stage="persistence",
                )

            features[window_name] = window_features

        return features

    def _filter_by_time(
        self,
        events: list[dict[str, Any]],
        window_seconds: int,
    ) -> list[dict[str, Any]]:
        """Filter events within time window."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - window_seconds

        return [
            e for e in events
            if e.get("timestamp", 0) >= cutoff
        ]

    def _extract_features(
        self,
        wallet: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract features from events."""
        if not events:
            return self._empty_features()

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))

        # Compute features
        volume = sum(e.get("amount", 0) for e in events)
        tx_frequency = len(events)
        avg_interval = self._compute_avg_interval(sorted_events)
        token_diversity = self._compute_token_diversity(events)
        buy_sell_ratio = self._compute_buy_sell_ratio(events)
        buy_count = sum(1 for e in events if e.get("event_type") == "BUY")
        sell_count = sum(1 for e in events if e.get("event_type") == "SELL")
        transfer_count = sum(1 for e in events if e.get("event_type") == "TRANSFER")

        return {
            "wallet": wallet,
            "volume": volume,
            "tx_frequency": tx_frequency,
            "avg_interval": avg_interval,
            "token_diversity": token_diversity,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "transfer_count": transfer_count,
            "buy_sell_ratio": buy_sell_ratio,
            "interaction_score": self._compute_interaction_score(events),
            "first_seen": sorted_events[0].get("timestamp", 0) if sorted_events else 0,
            "last_seen": sorted_events[-1].get("timestamp", 0) if sorted_events else 0,
        }

    def _compute_avg_interval(self, events: list[dict[str, Any]]) -> float:
        """Compute average interval between events."""
        if len(events) < 2:
            return float("inf")

        timestamps = [e.get("timestamp", 0) for e in events]
        intervals = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

        if not intervals:
            return float("inf")

        return sum(intervals) / len(intervals)

    def _compute_token_diversity(self, events: list[dict[str, Any]]) -> int:
        """Compute number of unique tokens."""
        tokens = set()
        for e in events:
            if e.get("token"):
                tokens.add(e["token"])
            if e.get("token_in"):
                tokens.add(e["token_in"])
            if e.get("token_out"):
                tokens.add(e["token_out"])
        return len(tokens)

    def _compute_buy_sell_ratio(self, events: list[dict[str, Any]]) -> float:
        """Compute buy/sell ratio."""
        buys = sum(1 for e in events if e.get("event_type") == "BUY")
        sells = sum(1 for e in events if e.get("event_type") == "SELL")
        if sells == 0:
            return float("inf") if buys > 0 else 0.0
        return buys / sells

    def _compute_interaction_score(self, events: list[dict[str, Any]]) -> float:
        """Compute interaction score."""
        volume = sum(e.get("amount", 0) for e in events)
        frequency = len(events)
        volume_score = min(1.0, volume / 10000)
        frequency_score = min(1.0, frequency / 100)
        return (volume_score + frequency_score) / 2

    def _empty_features(self) -> dict[str, Any]:
        """Return empty features."""
        return {
            "wallet": "",
            "volume": 0.0,
            "tx_frequency": 0,
            "avg_interval": float("inf"),
            "token_diversity": 0,
            "buy_count": 0,
            "sell_count": 0,
            "transfer_count": 0,
            "buy_sell_ratio": 0.0,
            "interaction_score": 0.0,
            "first_seen": 0,
            "last_seen": 0,
        }
