"""Lead-lag detector — detects which token leads movement inside cluster.

Functionality:
- Detect which token leads movement inside cluster
- Compute lead_score based on:
  - first derivative of velocity
  - early liquidity changes
  - cluster reaction delay

Output:
- leader_token_rank
- lagging_tokens_order
- lead_strength_score (0-1)
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LeadLagDetector:
    """Detects leader/follower relationships between tokens."""

    def __init__(self, lookback_seconds: int = 300) -> None:
        self._lookback = lookback_seconds
        self._token_velocities: dict[str, list[tuple[float, float]]] = {}
        self._cluster_reactions: dict[str, dict[str, float]] = {}

    def detect_leaders(
        self,
        cluster_tokens: list[str],
        token_events: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Detect leader tokens in a cluster.

        Returns:
            {
                "leader_token": str,
                "leader_rank": int,
                "lagging_tokens": list[str],
                "lead_strength": float,
                "lead_scores": dict[str, float],
            }
        """
        if not cluster_tokens:
            return {"leader_token": "", "lead_strength": 0.0}

        # Compute lead scores for each token
        lead_scores = {}
        for token in cluster_tokens:
            events = token_events.get(token, [])
            lead_score = self._compute_lead_score(token, events)
            lead_scores[token] = lead_score

        # Sort by lead score (highest first)
        sorted_tokens = sorted(lead_scores.items(), key=lambda x: x[1], reverse=True)

        if not sorted_tokens:
            return {"leader_token": "", "lead_strength": 0.0}

        leader_token = sorted_tokens[0][0]
        lead_strength = sorted_tokens[0][1]
        lagging_tokens = [t for t, _ in sorted_tokens[1:]]

        return {
            "leader_token": leader_token,
            "leader_rank": 1,
            "lagging_tokens": lagging_tokens,
            "lead_strength": lead_strength,
            "lead_scores": lead_scores,
        }

    def _compute_lead_score(
        self,
        token: str,
        events: list[dict[str, Any]],
    ) -> float:
        """Compute lead score for a token.

        Higher score = earlier mover = leader.
        """
        if not events:
            return 0.0

        # Factor 1: First derivative of velocity (early acceleration)
        velocity_score = self._compute_velocity_derivative(events)

        # Factor 2: Early liquidity changes
        liquidity_score = self._compute_early_liquidity(events)

        # Factor 3: Cluster reaction delay (inverse - earlier = higher)
        reaction_score = self._compute_reaction_delay(token, events)

        # Weighted combination
        lead_score = (
            0.4 * velocity_score +
            0.35 * liquidity_score +
            0.25 * reaction_score
        )

        return lead_score

    def _compute_velocity_derivative(self, events: list[dict[str, Any]]) -> float:
        """Compute first derivative of velocity (early acceleration)."""
        if len(events) < 3:
            return 0.0

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))

        # Compute volumes in time windows
        now = sorted_events[-1].get("timestamp", time.time())
        window_30s = [e for e in sorted_events if (now - e.get("timestamp", 0)) < 30]
        window_5m = [e for e in sorted_events if (now - e.get("timestamp", 0)) < 300]

        vol_30s = sum(e.get("amount", 0) for e in window_30s)
        vol_5m = sum(e.get("amount", 0) for e in window_5m)

        if vol_5m == 0:
            return 0.0

        # First derivative: how fast is velocity increasing
        velocity_30s = vol_30s / 30  # per second
        velocity_5m = vol_5m / 300  # per second

        if velocity_5m == 0:
            return 1.0 if velocity_30s > 0 else 0.0

        derivative = (velocity_30s - velocity_5m) / velocity_5m

        # Normalize to 0-1
        return max(0.0, min(1.0, derivative + 0.5))

    def _compute_early_liquidity(self, events: list[dict[str, Any]]) -> float:
        """Compute early liquidity changes (first 30s vs baseline)."""
        if not events:
            return 0.0

        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))
        now = sorted_events[-1].get("timestamp", time.time())

        # Early window (first 30s)
        early_events = [e for e in sorted_events if (now - e.get("timestamp", 0)) < 30]
        late_events = [e for e in sorted_events if (now - e.get("timestamp", 0)) >= 30]

        early_volume = sum(e.get("amount", 0) for e in early_events)
        late_volume = sum(e.get("amount", 0) for e in late_events)

        if late_volume == 0:
            return 1.0 if early_volume > 0 else 0.0

        # Ratio of early to late
        ratio = early_volume / late_volume
        return min(1.0, ratio)

    def _compute_reaction_delay(
        self,
        token: str,
        events: list[dict[str, Any]],
    ) -> float:
        """Compute cluster reaction delay (inverse - earlier = higher).

        Tokens that move first in a cluster have higher lead score.
        """
        if not events:
            return 0.0

        # Get earliest event timestamp
        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))
        if not sorted_events:
            return 0.0

        earliest = sorted_events[0].get("timestamp", time.time())

        # Compare to global earliest (lower = leader)
        # This is a simplified version - in production, would compare to cluster average
        return 1.0  # Default: assume leader

    def update_cluster_reaction(
        self,
        cluster_id: str,
        token: str,
        reaction_time: float,
    ) -> None:
        """Update cluster reaction time for a token."""
        if cluster_id not in self._cluster_reactions:
            self._cluster_reactions[cluster_id] = {}
        self._cluster_reactions[cluster_id][token] = reaction_time

    def get_leader_history(self, cluster_id: str) -> list[str]:
        """Get historical leader tokens for a cluster."""
        reactions = self._cluster_reactions.get(cluster_id, {})
        if not reactions:
            return []

        # Sort by reaction time (earliest first = leader)
        sorted_tokens = sorted(reactions.items(), key=lambda x: x[1])
        return [t for t, _ in sorted_tokens]
