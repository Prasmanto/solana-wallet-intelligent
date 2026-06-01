"""Temporal momentum model — computes momentum scoring for tokens.

Momentum formula:
    momentum = d(flow)/dt + d(cluster_activity)/dt + d(wallet_velocity)/dt

Signal:
    positive accelerating trend = early pump risk
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class MomentumModel:
    """Temporal momentum scoring engine with sliding window state."""

    def __init__(
        self,
        momentum_threshold: float = 0.3,
        cooldown_seconds: int = 300,
    ) -> None:
        self._momentum_threshold = momentum_threshold
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}
        self._momentum_history: dict[str, list[dict[str, Any]]] = {}
        # Sliding window state per token
        self._token_windows: dict[str, dict[str, list[float]]] = {}

    def compute(
        self,
        token: str,
        events: list[dict[str, Any]],
        token_flow: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Compute momentum score for a token.

        Uses sliding window state for temporal memory.
        """
        # Check cooldown
        if self._is_in_cooldown(token):
            return None

        # Update sliding window state
        self._update_windows(token, events)

        # Get window averages
        windows = self._token_windows.get(token, {})
        avg_5m = self._get_window_average(windows.get("5m", []))
        avg_15m = self._get_window_average(windows.get("15m", []))
        avg_1h = self._get_window_average(windows.get("1h", []))

        # Compute momentum as rate of change
        flow_momentum = self._compute_flow_momentum(avg_5m, avg_15m, avg_1h)
        cluster_momentum = self._compute_cluster_momentum(token_flow or {})
        velocity_momentum = self._compute_velocity_momentum(events)

        # Combine momentum components
        total_momentum = (
            flow_momentum * 0.4 +
            cluster_momentum * 0.3 +
            velocity_momentum * 0.3
        )

        # Check threshold
        if total_momentum < self._momentum_threshold:
            return None

        # Determine direction
        direction = "UP" if total_momentum > 0 else "DOWN"

        # Calculate score (normalized)
        score = min(1.0, total_momentum / 2.0)

        # Set cooldown
        self._last_signal[token] = time.time()

        return {
            "token": token,
            "signal": "MOMENTUM_BUILDUP",
            "momentum_score": total_momentum,
            "score": score,
            "direction": direction,
            "flow_momentum": flow_momentum,
            "cluster_momentum": cluster_momentum,
            "velocity_momentum": velocity_momentum,
            "confidence": self._calculate_confidence(total_momentum, len(events)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_flow_momentum(self, events: list[dict[str, Any]]) -> float:
        """Compute momentum from flow changes."""
        if len(events) < 2:
            return 0.0

        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)
        cutoff_15m = now - timedelta(minutes=15)

        events_5m = [e for e in events if self._get_timestamp(e) >= cutoff_5m]
        events_15m = [e for e in events if self._get_timestamp(e) >= cutoff_15m]

        flow_5m = sum(e.get("amount", 0) for e in events_5m)
        flow_15m = sum(e.get("amount", 0) for e in events_15m)

        if flow_15m == 0:
            return 0.0

        # Calculate rate of change
        rate_5m = flow_5m / 5  # per minute
        rate_15m = flow_15m / 15  # per minute

        if rate_15m == 0:
            return rate_5m > 0

        return (rate_5m - rate_15m) / rate_15m

    def _compute_cluster_momentum(self, token_flow: dict[str, Any]) -> float:
        """Compute momentum from cluster activity."""
        cluster_count = token_flow.get("cluster_count", 0)
        if cluster_count == 0:
            return 0.0

        # More clusters = higher momentum
        return min(1.0, cluster_count / 5)

    def _compute_velocity_momentum(self, events: list[dict[str, Any]]) -> float:
        """Compute momentum from transaction velocity."""
        if not events:
            return 0.0

        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)
        cutoff_1h = now - timedelta(hours=1)

        tx_5m = sum(1 for e in events if self._get_timestamp(e) >= cutoff_5m)
        tx_1h = sum(1 for e in events if self._get_timestamp(e) >= cutoff_1h)

        if tx_1h == 0:
            return 0.0

        velocity = tx_5m / max(tx_1h, 1)
        return min(1.0, velocity / 5)

    def _calculate_confidence(
        self,
        momentum: float,
        event_count: int,
    ) -> float:
        """Calculate confidence."""
        if momentum > 1.5 and event_count > 20:
            return 0.9
        elif momentum > 1.0 and event_count > 10:
            return 0.7
        elif momentum > 0.5:
            return 0.5
        return 0.3

    def _is_in_cooldown(self, token: str) -> bool:
        """Check cooldown."""
        last = self._last_signal.get(token, 0)
        return (time.time() - last) < self._cooldown

    def _update_windows(self, token: str, events: list[dict[str, Any]]) -> None:
        """Update sliding window state for a token."""
        if token not in self._token_windows:
            self._token_windows[token] = {"5m": [], "15m": [], "1h": []}

        windows = self._token_windows[token]
        now = time.time()

        # Add current event amounts to windows
        for event in events:
            amount = event.get("amount", 0)
            windows["5m"].append(amount)
            windows["15m"].append(amount)
            windows["1h"].append(amount)

        # Trim old values
        windows["5m"] = windows["5m"][-100:]  # Keep last 100 values
        windows["15m"] = windows["15m"][-300:]
        windows["1h"] = windows["1h"][-1000:]

    def _get_window_average(self, window: list[float]) -> float:
        """Get average value from a window."""
        if not window:
            return 0.0
        return sum(window) / len(window)

    def _compute_flow_momentum(
        self,
        avg_5m: float,
        avg_15m: float,
        avg_1h: float,
    ) -> float:
        """Compute momentum from flow changes using derivatives."""
        if avg_1h == 0:
            return 0.0

        # Rate of change between windows
        rate_5m = avg_5m / 5  # per minute
        rate_15m = avg_15m / 15  # per minute

        if rate_15m == 0:
            return rate_5m > 0

        # Derivative stability: consistent acceleration
        momentum = (rate_5m - rate_15m) / (rate_15m + 0.01)

        return max(0.0, momentum)  # Only positive momentum counts

    def _compute_velocity_momentum(self, events: list[dict[str, Any]]) -> float:
        """Compute momentum from transaction velocity."""
        if not events:
            return 0.0

        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)
        cutoff_1h = now - timedelta(hours=1)

        tx_5m = sum(1 for e in events if self._get_timestamp(e) >= cutoff_5m)
        tx_1h = sum(1 for e in events if self._get_timestamp(e) >= cutoff_1h)

        if tx_1h == 0:
            return 0.0

        velocity = tx_5m / max(tx_1h, 1)
        return min(1.0, velocity / 5)

    def _calculate_confidence(
        self,
        momentum: float,
        event_count: int,
    ) -> float:
        """Calculate confidence."""
        if momentum > 1.5 and event_count > 20:
            return 0.9
        elif momentum > 1.0 and event_count > 10:
            return 0.7
        elif momentum > 0.5:
            return 0.5
        return 0.3

    def _is_in_cooldown(self, token: str) -> bool:
        """Check cooldown."""
        last = self._last_signal.get(token, 0)
        return (time.time() - last) < self._cooldown

    def _get_timestamp(self, event: dict[str, Any]) -> datetime:
        """Extract timestamp."""
        ts = event.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.now(timezone.utc)

    def _get_window_average(self, window: list[float]) -> float:
        """Get average value from a window."""
        if not window:
            return 0.0
        return sum(window) / len(window)

    def _compute_flow_momentum(
        self,
        avg_5m: float,
        avg_15m: float,
        avg_1h: float,
    ) -> float:
        """Compute momentum from flow changes using derivatives."""
        if avg_1h == 0:
            return 0.0

        # Rate of change between windows
        rate_5m = avg_5m / 5  # per minute
        rate_15m = avg_15m / 15  # per minute

        if rate_15m == 0:
            return rate_5m > 0

        # Derivative stability: consistent acceleration
        momentum = (rate_5m - rate_15m) / (rate_15m + 0.01)

        return max(0.0, momentum)  # Only positive momentum counts
