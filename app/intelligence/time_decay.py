"""Time-decay engine — decays edge weights over time.

Formula:
    decayed_weight = weight * exp(-lambda * time_diff)

Where:
    lambda = configurable decay factor (default 0.01)
    time_diff = seconds since last interaction

Result:
- Old interactions become less relevant over time
- Recent interactions stay active
- Configurable decay rate
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Default decay factor (higher = faster decay)
DEFAULT_LAMBDA = 0.01


class TimeDecayEngine:
    """Applies time-based decay to edge weights."""

    def __init__(self, decay_factor: float = DEFAULT_LAMBDA) -> None:
        self._decay_factor = decay_factor

    def calculate_decayed_weight(
        self,
        weight: float,
        last_interaction: datetime,
        current_time: datetime | None = None,
    ) -> float:
        """Calculate decayed weight based on time difference.

        Args:
            weight: Original edge weight
            last_interaction: When the last interaction occurred
            current_time: Current time (default: now)

        Returns:
            Decayed weight value
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Ensure both times are timezone-aware
        if last_interaction.tzinfo is None:
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        time_diff = (current_time - last_interaction).total_seconds()
        decayed = weight * math.exp(-self._decay_factor * time_diff)

        return max(0.0, decayed)

    def apply_decay(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply decay to a list of edges.

        Args:
            edges: List of edge dictionaries with weight and last_interaction

        Returns:
            List of edges with updated decay_weight
        """
        now = datetime.now(timezone.utc)
        decayed_edges = []

        for edge in edges:
            weight = edge.get("weight", 0.0)
            last_interaction = edge.get("last_interaction")

            if last_interaction:
                decayed_weight = self.calculate_decayed_weight(weight, last_interaction, now)
            else:
                decayed_weight = weight

            decayed_edge = {
                **edge,
                "decay_weight": decayed_weight,
                "decay_applied_at": now.isoformat(),
            }
            decayed_edges.append(decayed_edge)

        return decayed_edges

    def should_expire(self, decayed_weight: float, threshold: float = 0.01) -> bool:
        """Check if a decayed weight is below expiration threshold."""
        return decayed_weight < threshold
