"""Token flow aggregator — aggregates wallet activity per token.

Tracks per token:
- inflow
- outflow
- active_wallets
- active_clusters
- net_liquidity_flow
- buy_pressure_ratio
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TokenFlowAggregator:
    """Aggregates wallet activity per token with historical state cache."""

    def __init__(self, history_window_seconds: int = 3600) -> None:
        self._history_window = history_window_seconds
        self._token_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "inflow": 0.0,
            "outflow": 0.0,
            "active_wallets": set(),
            "active_clusters": set(),
            "events": [],
            "last_updated": 0,
        })
        # Historical state cache for incremental updates
        self._historical_cache: dict[str, dict[str, Any]] = {}

    def update(self, event: dict[str, Any]) -> None:
        """Update token flow data with new event."""
        token = self._get_token(event)
        if not token:
            return

        wallet = event.get("wallet", "")
        event_type = event.get("event_type", "")
        amount = event.get("amount", 0)
        timestamp = event.get("timestamp", time.time())

        data = self._token_data[token]

        # Update flows
        if event_type in ("BUY", "TRANSFER"):
            data["inflow"] += amount
        elif event_type == "SELL":
            data["outflow"] += amount

        # Track active wallets
        if wallet:
            data["active_wallets"].add(wallet)

        # Store event for history
        data["events"].append({
            "wallet": wallet,
            "event_type": event_type,
            "amount": amount,
            "timestamp": timestamp,
        })

        data["last_updated"] = time.time()

    def update_cluster(self, token: str, cluster_id: str) -> None:
        """Update cluster activity for a token."""
        if token in self._token_data:
            self._token_data[token]["active_clusters"].add(cluster_id)

    def get_token_flow(self, token: str) -> dict[str, Any]:
        """Get aggregated flow data for a token."""
        data = self._token_data.get(token, self._empty_flow())

        # Clean old events
        now = time.time()
        data["events"] = [
            e for e in data["events"]
            if (now - e.get("timestamp", 0)) < self._history_window
        ]

        # Calculate metrics
        inflow = data["inflow"]
        outflow = data["outflow"]
        net_flow = inflow - outflow
        buy_pressure = inflow / (outflow + 1)

        return {
            "token": token,
            "inflow": inflow,
            "outflow": outflow,
            "net_flow": net_flow,
            "buy_pressure_ratio": buy_pressure,
            "wallet_count": len(data["active_wallets"]),
            "cluster_count": len(data["active_clusters"]),
            "wallets": list(data["active_wallets"]),
            "clusters": list(data["active_clusters"]),
            "event_count": len(data["events"]),
            "last_updated": data["last_updated"],
        }

    def get_all_tokens(self) -> list[str]:
        """Get all tracked tokens."""
        return list(self._token_data.keys())

    def get_token_count(self) -> int:
        """Get number of tracked tokens."""
        return len(self._token_data)

    def _get_token(self, event: dict[str, Any]) -> str | None:
        """Extract token from event."""
        token = event.get("token", "")
        if not token:
            token = event.get("token_in", "")
        if not token:
            token = event.get("token_out", "")
        return token if token else None

    def _empty_flow(self) -> dict[str, Any]:
        """Return empty flow data."""
        return {
            "inflow": 0.0,
            "outflow": 0.0,
            "active_wallets": set(),
            "active_clusters": set(),
            "events": [],
            "last_updated": 0,
        }

    def export_flow(self) -> dict[str, dict[str, Any]]:
        """Export all token flow data."""
        result = {}
        for token in self._token_data:
            result[token] = self.get_token_flow(token)
        return result

    def get_historical_state(self, token: str) -> dict[str, Any]:
        """Get historical state for a token."""
        return self._historical_cache.get(token, {})

    def update_historical_state(self, token: str, metrics: dict[str, Any]) -> None:
        """Update historical state for a token."""
        if token not in self._historical_cache:
            self._historical_cache[token] = {
                "snapshots": [],
                "last_updated": 0,
            }

        cache = self._historical_cache[token]
        cache["snapshots"].append({
            "timestamp": time.time(),
            "metrics": metrics,
        })
        cache["last_updated"] = time.time()

        # Keep only recent snapshots
        if len(cache["snapshots"]) > 100:
            cache["snapshots"] = cache["snapshots"][-50:]
