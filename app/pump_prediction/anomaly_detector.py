"""Anomaly detector — detects abnormal deviation vs baseline behavior.

Baseline metrics:
- avg_volume_1h
- avg_wallet_count
- avg_cluster_activity

Anomaly score:
    anomaly_score = current_activity / historical_avg

Trigger:
    anomaly_score > 2.0 → abnormal activity
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AnomalyDetector:
    """Detects abnormal token activity vs baseline."""

    def __init__(
        self,
        anomaly_threshold: float = 0.3,
        baseline_window_minutes: int = 60,
        cooldown_seconds: int = 300,
    ) -> None:
        self._anomaly_threshold = anomaly_threshold
        self._baseline_window = baseline_window_minutes
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}
        self._baseline_history: dict[str, list[dict[str, Any]]] = {}

    def detect(
        self,
        token: str,
        current_events: list[dict[str, Any]],
        historical_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Detect anomalous activity for a token.

        Args:
            token: Token address
            current_events: Recent events (last 5-15 min)
            historical_events: Historical events (last 1h+)

        Returns:
            Signal dict if anomaly detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(token):
            return None

        # Calculate current metrics
        current_metrics = self._calculate_metrics(current_events)

        # Calculate baseline metrics
        if historical_events:
            baseline_metrics = self._calculate_metrics(historical_events)
        else:
            baseline_metrics = self._get_baseline(token)

        # Update baseline history
        self._update_baseline(token, current_metrics)

        # Calculate anomaly score
        anomaly_score = self._calculate_anomaly_score(
            current_metrics,
            baseline_metrics,
        )

        if anomaly_score < self._anomaly_threshold:
            return None

        # Calculate confidence
        confidence = self._calculate_confidence(
            anomaly_score,
            len(current_events),
            current_metrics.get("wallet_count", 0),
        )

        # Set cooldown
        self._last_signal[token] = time.time()

        return {
            "token": token,
            "signal": "PRE_PUMP_ANOMALY",
            "anomaly_score": anomaly_score,
            "current_activity": current_metrics,
            "baseline_activity": baseline_metrics,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_metrics(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate activity metrics from events."""
        if not events:
            return {
                "volume": 0,
                "tx_count": 0,
                "wallet_count": 0,
                "avg_amount": 0,
            }

        volume = sum(e.get("amount", 0) for e in events)
        tx_count = len(events)
        wallets = set(e.get("wallet", "") for e in events if e.get("wallet"))
        avg_amount = volume / tx_count if tx_count > 0 else 0

        return {
            "volume": volume,
            "tx_count": tx_count,
            "wallet_count": len(wallets),
            "avg_amount": avg_amount,
        }

    def _calculate_anomaly_score(
        self,
        current: dict[str, Any],
        baseline: dict[str, Any],
    ) -> float:
        """Calculate anomaly score as ratio of current to baseline.

        Normalized to prevent score explosion.
        """
        if baseline.get("volume", 0) == 0:
            if current.get("volume", 0) > 0:
                return 2.0  # New activity when baseline is zero (capped)
            return 0.0

        volume_ratio = current.get("volume", 0) / baseline.get("volume", 1)
        tx_ratio = current.get("tx_count", 0) / max(baseline.get("tx_count", 1), 1)
        wallet_ratio = current.get("wallet_count", 0) / max(baseline.get("wallet_count", 1), 1)

        # Weighted average
        raw_score = (volume_ratio * 0.5) + (tx_ratio * 0.3) + (wallet_ratio * 0.2)

        # Normalize to prevent explosion (value / (value + k))
        k = 5.0
        normalized = raw_score / (raw_score + k)

        return normalized

    def _calculate_confidence(
        self,
        anomaly_score: float,
        event_count: int,
        wallet_count: int,
    ) -> float:
        """Calculate confidence."""
        if anomaly_score > 3.0 and wallet_count > 5:
            return 0.9
        elif anomaly_score > 2.0 and wallet_count > 3:
            return 0.7
        elif anomaly_score > 1.5:
            return 0.5
        return 0.3

    def _get_baseline(self, token: str) -> dict[str, Any]:
        """Get baseline metrics from history."""
        history = self._baseline_history.get(token, [])
        if not history:
            return {"volume": 0, "tx_count": 0, "wallet_count": 0, "avg_amount": 0}

        # Average of recent baselines
        volumes = [h.get("volume", 0) for h in history]
        tx_counts = [h.get("tx_count", 0) for h in history]
        wallet_counts = [h.get("wallet_count", 0) for h in history]

        return {
            "volume": sum(volumes) / len(volumes) if volumes else 0,
            "tx_count": sum(tx_counts) / len(tx_counts) if tx_counts else 0,
            "wallet_count": sum(wallet_counts) / len(wallet_counts) if wallet_counts else 0,
            "avg_amount": 0,
        }

    def _update_baseline(self, token: str, metrics: dict[str, Any]) -> None:
        """Update baseline history."""
        if token not in self._baseline_history:
            self._baseline_history[token] = []

        self._baseline_history[token].append(metrics)

        # Keep only recent history
        if len(self._baseline_history[token]) > 100:
            self._baseline_history[token] = self._baseline_history[token][-50:]

    def _is_in_cooldown(self, token: str) -> bool:
        """Check cooldown."""
        last = self._last_signal.get(token, 0)
        return (time.time() - last) < self._cooldown
