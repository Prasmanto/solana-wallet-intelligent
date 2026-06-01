"""Cluster convergence detector — detects multiple clusters entering same token.

Rule:
    Trigger if:
    - >= 2 clusters interacting with same token
    - within 5-15 min window
    - with positive net flow
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ClusterConvergenceDetector:
    """Detects cluster convergence on tokens."""

    def __init__(
        self,
        min_clusters: int = 2,
        window_minutes: int = 10,
        cooldown_seconds: int = 600,
    ) -> None:
        self._min_clusters = min_clusters
        self._window = window_minutes
        self._cooldown = cooldown_seconds
        self._last_signal: dict[str, float] = {}

    def detect(
        self,
        token: str,
        token_flow: dict[str, Any],
        cluster_events: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        """Detect cluster convergence on a token.

        Args:
            token: Token address
            token_flow: Aggregated token flow data
            cluster_events: Events grouped by cluster

        Returns:
            Signal dict if convergence detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(token):
            return None

        # Get active clusters for this token
        active_clusters = token_flow.get("clusters", [])

        if len(active_clusters) < self._min_clusters:
            return None

        # Check if clusters have recent activity on this token
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self._window)

        active_cluster_ids = []
        for cluster_id in active_clusters:
            cluster_wallets = cluster_events.get(cluster_id, [])
            # Check if any wallet in cluster has recent activity on this token
            has_activity = any(
                e.get("token") == token and
                self._get_timestamp(e) >= cutoff
                for e in cluster_wallets
            )
            if has_activity:
                active_cluster_ids.append(cluster_id)

        if len(active_cluster_ids) < self._min_clusters:
            return None

        # Calculate synchronization score
        sync_score = self._calculate_synchronization(
            active_cluster_ids,
            cluster_events,
            token,
        )

        # Check positive net flow
        net_flow = token_flow.get("net_flow", 0)
        if net_flow <= 0:
            return None

        # Calculate score and confidence
        score = self._calculate_score(sync_score, len(active_cluster_ids), net_flow)
        confidence = self._calculate_confidence(
            len(active_cluster_ids),
            sync_score,
            net_flow,
        )

        # Set cooldown
        self._last_signal[token] = time.time()

        return {
            "token": token,
            "signal": "CLUSTER_CONVERGENCE",
            "clusters": active_cluster_ids,
            "active_clusters": len(active_cluster_ids),
            "synchronized_score": sync_score,
            "net_flow": net_flow,
            "score": score,
            "confidence": confidence,
            "timestamp": now.isoformat(),
        }

    def _calculate_synchronization(
        self,
        cluster_ids: list[str],
        cluster_events: dict[str, list[dict[str, Any]]],
        token: str,
    ) -> float:
        """Calculate synchronization score across clusters."""
        if len(cluster_ids) < 2:
            return 0.0

        # Check if clusters have similar activity patterns
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=5)

        activity_counts = []
        for cluster_id in cluster_ids:
            events = cluster_events.get(cluster_id, [])
            recent = sum(
                1 for e in events
                if e.get("token") == token and
                self._get_timestamp(e) >= cutoff
            )
            activity_counts.append(recent)

        # Calculate variance
        if not activity_counts:
            return 0.0

        avg = sum(activity_counts) / len(activity_counts)
        variance = sum((x - avg) ** 2 for x in activity_counts) / len(activity_counts)

        # Lower variance = higher synchronization
        if variance < 1:
            return 0.9
        elif variance < 5:
            return 0.7
        elif variance < 10:
            return 0.5
        return 0.3

    def _calculate_score(
        self,
        sync_score: float,
        cluster_count: int,
        net_flow: float,
    ) -> float:
        """Calculate convergence score."""
        sync_component = sync_score * 0.4
        count_component = min(1.0, cluster_count / 5) * 0.3
        flow_component = min(1.0, net_flow / 5000) * 0.3
        return sync_component + count_component + flow_component

    def _calculate_confidence(
        self,
        cluster_count: int,
        sync_score: float,
        net_flow: float,
    ) -> float:
        """Calculate confidence."""
        if cluster_count >= 3 and sync_score > 0.7 and net_flow > 2000:
            return 0.9
        elif cluster_count >= 2 and sync_score > 0.5:
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
