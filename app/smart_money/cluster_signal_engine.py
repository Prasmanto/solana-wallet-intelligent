"""Cluster signal engine — detects cluster-level coordinated activity.

Analyzes cluster behavior from wallet_clusters and wallet_edges.

Signal conditions:
    multiple wallets in same cluster show:
    - velocity spike
    - positive net flow
    - synchronized activity (within 5-10 min window)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from app.smart_money.signal_models import ClusterSignal

logger = structlog.get_logger(__name__)


class ClusterSignalEngine:
    """Detects cluster-level coordinated activity."""

    def __init__(
        self,
        min_active_wallets: int = 3,
        sync_window_minutes: int = 10,
        cooldown_seconds: int = 900,
    ) -> None:
        self._min_active_wallets = min_active_wallets
        self._sync_window = sync_window_minutes
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}

    def detect(
        self,
        cluster_id: str,
        wallet_events: dict[str, list[dict[str, Any]]],
    ) -> ClusterSignal | None:
        """Detect cluster-level coordinated activity.

        Args:
            cluster_id: Cluster identifier
            wallet_events: Dict of wallet -> events mapping

        Returns:
            ClusterSignal if detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(cluster_id):
            return None

        if not wallet_events:
            return None

        # Analyze each wallet's activity
        wallet_analyses = []
        for wallet, events in wallet_events.items():
            analysis = self._analyze_wallet_activity(wallet, events)
            wallet_analyses.append(analysis)

        # Filter active wallets (with velocity spike or positive flow)
        active_wallets = [
            w for w in wallet_analyses
            if w["has_velocity_spike"] or w["has_positive_flow"]
        ]

        if len(active_wallets) < self._min_active_wallets:
            return None

        # Calculate synchronized activity
        sync_score = self._calculate_synchronization(active_wallets)

        if sync_score < 0.5:
            return None

        # Calculate overall metrics
        velocity_score = sum(w["velocity_score"] for w in active_wallets) / len(active_wallets)
        flow_score = sum(w["flow_score"] for w in active_wallets) / len(active_wallets)

        # Calculate final score
        score = self._calculate_cluster_score(sync_score, velocity_score, flow_score)
        confidence = self._calculate_confidence(
            len(active_wallets),
            len(wallet_events),
            sync_score,
        )

        # Set cooldown
        self._last_signal[cluster_id] = time.time()

        active_wallet_list = [w["wallet"] for w in active_wallets]

        signal = ClusterSignal(
            cluster_id=cluster_id,
            active_wallets=len(active_wallets),
            total_wallets=len(wallet_events),
            synchronized_score=sync_score,
            velocity_score=velocity_score,
            flow_score=flow_score,
            score=score,
            confidence=confidence,
            wallets=active_wallet_list,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "cluster.activity_detected",
            cluster_id=cluster_id[:16],
            active_wallets=len(active_wallets),
            sync_score=sync_score,
            score=score,
            stage="cluster",
        )

        return signal

    def _analyze_wallet_activity(
        self,
        wallet: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze activity for a single wallet."""
        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)
        cutoff_1h = now - timedelta(hours=1)

        events_5m = [e for e in events if self._get_timestamp(e) >= cutoff_5m]
        events_1h = [e for e in events if self._get_timestamp(e) >= cutoff_1h]

        tx_5m = len(events_5m)
        tx_1h = len(events_1h)

        # Velocity check
        velocity_ratio = tx_5m / max(tx_1h, 1)
        has_velocity_spike = velocity_ratio > 3.0

        # Flow check
        inflow = sum(e.get("amount", 0) for e in events_5m if e.get("event_type") in ("BUY", "TRANSFER"))
        outflow = sum(e.get("amount", 0) for e in events_5m if e.get("event_type") == "SELL")
        net_flow = inflow - outflow
        has_positive_flow = net_flow > 0

        return {
            "wallet": wallet,
            "tx_5m": tx_5m,
            "tx_1h": tx_1h,
            "velocity_ratio": velocity_ratio,
            "has_velocity_spike": has_velocity_spike,
            "inflow": inflow,
            "outflow": outflow,
            "net_flow": net_flow,
            "has_positive_flow": has_positive_flow,
            "velocity_score": min(1.0, velocity_ratio / 5.0),
            "flow_score": min(1.0, max(0, net_flow) / 1000),
        }

    def _calculate_synchronization(
        self,
        active_wallets: list[dict[str, Any]],
    ) -> float:
        """Calculate synchronization score across active wallets."""
        if len(active_wallets) < 2:
            return 0.0

        # Check if wallets have similar activity patterns
        # (simplified: check if velocity scores are similar)
        velocity_scores = [w["velocity_score"] for w in active_wallets]
        avg_velocity = sum(velocity_scores) / len(velocity_scores)

        # Calculate variance
        variance = sum((s - avg_velocity) ** 2 for s in velocity_scores) / len(velocity_scores)

        # Lower variance = higher synchronization
        if variance < 0.01:
            return 0.9
        elif variance < 0.05:
            return 0.7
        elif variance < 0.1:
            return 0.5
        else:
            return 0.3

    def _calculate_cluster_score(
        self,
        sync_score: float,
        velocity_score: float,
        flow_score: float,
    ) -> float:
        """Calculate overall cluster signal score."""
        return (sync_score * 0.4) + (velocity_score * 0.3) + (flow_score * 0.3)

    def _calculate_confidence(
        self,
        active_wallets: int,
        total_wallets: int,
        sync_score: float,
    ) -> float:
        """Calculate confidence based on cluster metrics."""
        if active_wallets >= 5 and sync_score > 0.7:
            return 0.9
        elif active_wallets >= 3 and sync_score > 0.5:
            return 0.75
        return 0.5

    def _is_in_cooldown(self, cluster_id: str) -> bool:
        """Check if cluster is in cooldown period."""
        last_signal_time = self._last_signal.get(cluster_id, 0)
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
