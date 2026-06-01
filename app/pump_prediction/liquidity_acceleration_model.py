"""Liquidity acceleration model — regime-aware adaptive detection.

Upgraded with:
- Adaptive threshold based on volatility
- Burst window detection
- Velocity derivative checking
- Soft signal triggering (sigmoid)
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def sigmoid(x: float) -> float:
    """Sigmoid function for soft signal triggering."""
    return 1 / (1 + math.exp(-x))


class LiquidityAccelerationModel:
    """Regime-aware liquidity acceleration detector."""

    def __init__(
        self,
        base_threshold: float = 0.6,
        cooldown_seconds: int = 300,
    ) -> None:
        self._base_threshold = base_threshold
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}

    def detect(
        self,
        token: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Detect liquidity acceleration with adaptive threshold.

        Uses:
        - Adaptive threshold based on volatility
        - Burst window detection
        - Velocity derivative checking
        - Soft signal triggering
        """
        # Check cooldown
        if self._is_in_cooldown(token):
            return None

        # Calculate flow across windows
        windows = self._calculate_flows(events)

        if len(windows) < 2:
            return None

        # Detect burst mode
        burst_mode = self._detect_burst(windows)

        # Calculate volatility factor
        volatility_factor = self._calculate_volatility(windows)

        # Calculate window compression factor
        compression_factor = self._calculate_compression(windows)

        # Adaptive threshold
        adaptive_threshold = self._base_threshold * volatility_factor * compression_factor

        # Calculate acceleration
        accelerations = []
        for i in range(1, len(windows)):
            prev_flow = windows[i - 1]["inflow"]
            curr_flow = windows[i]["inflow"]

            if prev_flow > 0:
                acceleration = (curr_flow - prev_flow) / prev_flow
            else:
                acceleration = 1.0 if curr_flow > 0 else 0.0

            accelerations.append(acceleration)

        # Check if acceleration is positive
        increasing_count = sum(1 for a in accelerations if a > 0)

        # Calculate average acceleration
        avg_acceleration = sum(accelerations) / len(accelerations) if accelerations else 0

        # Velocity derivative check
        velocity_check = self._check_velocity_derivative(windows)

        # Apply burst multiplier
        if burst_mode:
            avg_acceleration *= 1.8

        # Calculate raw score
        raw_score = avg_acceleration

        # Apply velocity derivative boost
        if velocity_check:
            raw_score *= 1.3

        # Soft signal triggering using sigmoid
        signal_strength = sigmoid(raw_score - adaptive_threshold)

        # Check if signal is strong enough
        if signal_strength < 0.3:
            return None

        # Calculate final score
        score = min(1.0, signal_strength)

        # Set cooldown
        self._last_signal[token] = time.time()

        return {
            "token": token,
            "signal": "LIQUIDITY_ACCELERATION",
            "score": score,
            "confidence": self._calculate_confidence(increasing_count, len(windows)),
            "acceleration": avg_acceleration,
            "increasing_windows": increasing_count,
            "burst_mode": burst_mode,
            "velocity_check": velocity_check,
            "adaptive_threshold": adaptive_threshold,
            "trend": "ACCELERATING",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _detect_burst(self, windows: list[dict[str, Any]]) -> bool:
        """Detect if activity is compressed into short window.

        Burst detected when:
        events_in_60s > events_in_5min_avg * 2
        """
        if len(windows) < 2:
            return False

        # Get 60s window (first window if we have 4+ windows)
        events_60s = windows[0]["event_count"] if len(windows) >= 1 else 0

        # Get 5min average
        events_5min = windows[1]["event_count"] if len(windows) >= 2 else 0
        events_15min = windows[2]["event_count"] if len(windows) >= 3 else 0

        avg_5min = (events_5min + events_15min) / 2 if (events_5min + events_15min) > 0 else 1

        # Burst if 60s events > 2x average
        return events_60s > avg_5min * 2

    def _calculate_volatility(self, windows: list[dict[str, Any]]) -> float:
        """Calculate volatility factor from flow variance.

        Higher volatility → lower threshold needed.
        """
        if len(windows) < 2:
            return 1.0

        flows = [w.get("inflow", 0) for w in windows]
        if not flows or max(flows) == 0:
            return 1.0

        avg = sum(flows) / len(flows)
        variance = sum((f - avg) ** 2 for f in flows) / len(flows)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        # Normalize: higher volatility → lower threshold
        if avg > 0:
            cv = std_dev / avg  # coefficient of variation
            # cv > 1 means high volatility → threshold * 0.5
            # cv < 0.3 means low volatility → threshold * 1.2
            if cv > 1.0:
                return 0.5
            elif cv > 0.3:
                return 1.0
            else:
                return 1.2
        return 1.0

    def _calculate_compression(self, windows: list[dict[str, Any]]) -> float:
        """Calculate window compression factor.

        Compressed windows (many events in short time) → lower threshold.
        """
        if len(windows) < 2:
            return 1.0

        # Compare 5min vs 15min window
        events_5m = windows[1]["event_count"] if len(windows) >= 2 else 0
        events_15m = windows[2]["event_count"] if len(windows) >= 3 else events_5m

        if events_15m == 0:
            return 1.0

        # Compression ratio
        ratio = events_5m / events_15m

        # High compression (>0.5) → lower threshold
        if ratio > 0.5:
            return 0.7
        elif ratio > 0.3:
            return 0.9
        return 1.0

    def _check_velocity_derivative(self, windows: list[dict[str, Any]]) -> bool:
        """Check if velocity is accelerating (positive derivative).

        Returns True if:
        velocity = current_volume - previous_volume
        acceleration = velocity - previous_velocity
        acceleration > 0 AND velocity > baseline * 1.3
        """
        if len(windows) < 3:
            return False

        # Calculate velocities (change in flow between windows)
        flows = [w.get("inflow", 0) for w in windows]
        velocities = [flows[i] - flows[i-1] for i in range(1, len(flows))]

        if len(velocities) < 2:
            return False

        # Calculate accelerations (change in velocity)
        accelerations = [velocities[i] - velocities[i-1] for i in range(1, len(velocities))]

        if not accelerations:
            return False

        # Check if acceleration is positive and velocity is above baseline
        avg_velocity = sum(velocities) / len(velocities) if velocities else 0
        latest_acceleration = accelerations[-1] if accelerations else 0

        # Baseline is the average of all velocities
        baseline = avg_velocity

        return latest_acceleration > 0 and avg_velocity > baseline * 1.3

    def _calculate_flows(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Calculate flows across time windows."""
        windows = []
        now = datetime.now(timezone.utc)

        for minutes in [5, 15, 30, 60]:
            cutoff = now - timedelta(minutes=minutes)
            window_events = [
                e for e in events
                if self._get_timestamp(e) >= cutoff
            ]

            inflow = sum(
                e.get("amount", 0)
                for e in window_events
                if e.get("event_type") in ("BUY", "TRANSFER")
            )

            windows.append({
                "minutes": minutes,
                "inflow": inflow,
                "event_count": len(window_events),
            })

        return windows

    def _calculate_score(
        self,
        avg_acceleration: float,
        increasing_count: int,
        window_count: int,
    ) -> float:
        """Calculate acceleration score."""
        accel_score = min(1.0, avg_acceleration / 3.0)
        sustain_score = min(1.0, increasing_count / window_count)
        return (accel_score * 0.6) + (sustain_score * 0.4)

    def _calculate_confidence(
        self,
        increasing_count: int,
        window_count: int,
    ) -> float:
        """Calculate confidence."""
        ratio = increasing_count / max(window_count, 1)
        if ratio > 0.75:
            return 0.9
        elif ratio > 0.5:
            return 0.7
        return 0.5

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
