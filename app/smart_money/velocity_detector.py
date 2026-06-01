"""Velocity detector — detects sudden increases in wallet activity.

Velocity calculation:
    velocity = tx_count(last_5m) / tx_count(last_1h)

Signal conditions:
    velocity_ratio > 3.0
    AND volume increases > 2x baseline
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from app.smart_money.signal_models import VelocitySignal

logger = structlog.get_logger(__name__)


class VelocityDetector:
    """Detects velocity spikes in wallet activity."""

    def __init__(
        self,
        velocity_threshold: float = 3.0,
        volume_threshold: float = 2.0,
        cooldown_seconds: int = 300,
    ) -> None:
        self._velocity_threshold = velocity_threshold
        self._volume_threshold = volume_threshold
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}

    def detect(
        self,
        wallet: str,
        events: list[dict[str, Any]],
    ) -> VelocitySignal | None:
        """Detect velocity spike for a wallet.

        Args:
            wallet: Wallet address
            events: List of recent events

        Returns:
            VelocitySignal if spike detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(wallet):
            return None

        # Separate events by time window
        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)
        cutoff_1h = now - timedelta(hours=1)

        events_5m = [e for e in events if self._get_timestamp(e) >= cutoff_5m]
        events_1h = [e for e in events if self._get_timestamp(e) >= cutoff_1h]

        tx_5m = len(events_5m)
        tx_1h = len(events_1h)

        if tx_1h == 0:
            return None

        # Calculate velocity ratio
        velocity_ratio = tx_5m / max(tx_1h, 1)

        # Calculate volume increase
        volume_5m = sum(e.get("amount", 0) for e in events_5m)
        volume_1h = sum(e.get("amount", 0) for e in events_1h)
        volume_increase = volume_5m / max(volume_1h, 1)

        # Check thresholds
        if velocity_ratio < self._velocity_threshold:
            return None
        if volume_increase < self._volume_threshold:
            return None

        # Calculate score
        score = self._calculate_score(velocity_ratio, volume_increase)
        confidence = self._calculate_confidence(tx_5m, tx_1h, volume_5m)

        # Set cooldown
        self._last_signal[wallet] = time.time()

        signal = VelocitySignal(
            wallet=wallet,
            velocity_ratio=velocity_ratio,
            tx_5m=tx_5m,
            tx_1h=tx_1h,
            baseline=tx_1h // 12,  # Approximate per-5min baseline
            volume_increase=volume_increase,
            score=score,
            confidence=confidence,
            timestamp=now.isoformat(),
        )

        logger.info(
            "velocity.spike_detected",
            wallet=wallet[:16],
            velocity_ratio=velocity_ratio,
            score=score,
            stage="velocity",
        )

        return signal

    def _calculate_score(self, velocity_ratio: float, volume_increase: float) -> float:
        """Calculate velocity score (0.0 - 1.0)."""
        # Normalize ratios to 0-1 range
        vel_score = min(1.0, velocity_ratio / 10.0)
        vol_score = min(1.0, volume_increase / 5.0)

        # Weighted combination
        return (vel_score * 0.6) + (vol_score * 0.4)

    def _calculate_confidence(self, tx_5m: int, tx_1h: int, volume_5m: float) -> float:
        """Calculate confidence based on data quality."""
        if tx_1h < 5:
            return 0.3  # Low confidence with few data points
        if tx_5m < 3:
            return 0.5
        if volume_5m > 1000:
            return 0.9
        return 0.7

    def _is_in_cooldown(self, wallet: str) -> bool:
        """Check if wallet is in cooldown period."""
        last_signal_time = self._last_signal.get(wallet, 0)
        return (time.time() - last_signal_time) < self._cooldown

    def _get_timestamp(self, event: dict[str, Any]) -> datetime:
        """Extract timestamp from event."""
        ts = event.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)
