"""Liquidity flow tracker — tracks inflow vs outflow per wallet.

Tracks:
- token inflow
- token outflow
- net accumulation
- flow ratio across time windows

Signal conditions:
    flow_ratio > 2.5
    AND sustained over 3 windows (5m, 15m, 1h)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from app.smart_money.signal_models import LiquiditySignal

logger = structlog.get_logger(__name__)


class LiquidityFlowTracker:
    """Tracks liquidity flow patterns for wallets."""

    def __init__(
        self,
        flow_ratio_threshold: float = 2.5,
        sustained_windows: int = 3,
        cooldown_seconds: int = 600,
    ) -> None:
        self._flow_ratio_threshold = flow_ratio_threshold
        self._sustained_windows = sustained_windows
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}
        self._flow_history: dict[str, list[dict[str, Any]]] = {}

    def track(
        self,
        wallet: str,
        events: list[dict[str, Any]],
    ) -> LiquiditySignal | None:
        """Track liquidity flow for a wallet.

        Args:
            wallet: Wallet address
            events: List of recent events

        Returns:
            LiquiditySignal if accumulation detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(wallet):
            return None

        # Calculate flows across time windows
        windows = self._calculate_flows(events)

        # Check if sustained across windows
        sustained_count = sum(1 for w in windows if w["flow_ratio"] > self._flow_ratio_threshold)

        if sustained_count < self._sustained_windows:
            return None

        # Get latest window metrics
        latest = windows[-1] if windows else self._empty_window()

        # Calculate score and confidence
        score = self._calculate_score(latest, sustained_count)
        confidence = self._calculate_confidence(sustained_count, latest["net_flow"])

        # Set cooldown
        self._last_signal[wallet] = time.time()

        signal = LiquiditySignal(
            wallet=wallet,
            net_flow=latest["net_flow"],
            inflow=latest["inflow"],
            outflow=latest["outflow"],
            flow_ratio=latest["flow_ratio"],
            sustained_windows=sustained_count,
            score=score,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "liquidity.accumulation_detected",
            wallet=wallet[:16],
            net_flow=latest["net_flow"],
            flow_ratio=latest["flow_ratio"],
            sustained=sustained_count,
            score=score,
            stage="liquidity",
        )

        return signal

    def _calculate_flows(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Calculate flows across multiple time windows."""
        windows = []
        now = datetime.now(timezone.utc)

        for minutes in [5, 15, 60]:
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
            outflow = sum(
                e.get("amount", 0)
                for e in window_events
                if e.get("event_type") in ("SELL",)
            )

            net_flow = inflow - outflow
            flow_ratio = inflow / (outflow + 1)

            windows.append({
                "minutes": minutes,
                "inflow": inflow,
                "outflow": outflow,
                "net_flow": net_flow,
                "flow_ratio": flow_ratio,
                "event_count": len(window_events),
            })

        return windows

    def _calculate_score(
        self,
        latest_window: dict[str, Any],
        sustained_count: int,
    ) -> float:
        """Calculate liquidity score."""
        flow_score = min(1.0, latest_window["flow_ratio"] / 5.0)
        sustained_score = min(1.0, sustained_count / 3.0)
        volume_score = min(1.0, latest_window["net_flow"] / 10000)

        return (flow_score * 0.4) + (sustained_score * 0.3) + (volume_score * 0.3)

    def _calculate_confidence(
        self,
        sustained_count: int,
        net_flow: float,
    ) -> float:
        """Calculate confidence based on signal strength."""
        if sustained_count >= 3 and net_flow > 5000:
            return 0.9
        elif sustained_count >= 3:
            return 0.75
        elif sustained_count >= 2:
            return 0.6
        return 0.4

    def _is_in_cooldown(self, wallet: str) -> bool:
        """Check if wallet is in cooldown period."""
        last_signal_time = self._last_signal.get(wallet, 0)
        return (time.time() - last_signal_time) < self._cooldown

    def _empty_window(self) -> dict[str, Any]:
        """Return empty window metrics."""
        return {
            "minutes": 0,
            "inflow": 0,
            "outflow": 0,
            "net_flow": 0,
            "flow_ratio": 0,
            "event_count": 0,
        }

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
