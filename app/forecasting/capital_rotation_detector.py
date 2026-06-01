"""Capital rotation detector — detects capital flow between clusters."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.forecasting.forecast_models import CapitalRotationSignal

logger = structlog.get_logger(__name__)


class CapitalRotationDetector:
    """Detects capital flow moving from one cluster to another."""

    def __init__(self, lookback_seconds: int = 300) -> None:
        self._lookback = lookback_seconds
        self._cluster_liquidity: dict[str, list[tuple[float, float]]] = {}

    def detect_rotation(
        self,
        cluster_liquidity: dict[str, float],
        cluster_history: dict[str, list[tuple[float, float]]],
    ) -> list[CapitalRotationSignal]:
        """Detect capital rotation between clusters."""
        signals = []

        # Compute liquidity changes for each cluster
        changes = {}
        for cluster_id, current_liquidity in cluster_liquidity.items():
            history = cluster_history.get(cluster_id, [])
            if len(history) < 2:
                continue

            # Get recent liquidity (last 5 minutes)
            recent = [v for t, v in history if time.time() - t < 300]
            if recent:
                avg_recent = sum(recent) / len(recent)
                change = (current_liquidity - avg_recent) / max(avg_recent, 1)
                changes[cluster_id] = change

        # Find warming and cooling clusters
        warming = {k: v for k, v in changes.items() if v > 0.1}
        cooling = {k: v for k, v in changes.items() if v < -0.1}

        # Match warming and cooling clusters
        for source_id, source_change in cooling.items():
            for target_id, target_change in warming.items():
                if source_id != target_id:
                    rotation_strength = abs(source_change) * abs(target_change)

                    # Check if smart money is moving
                    smart_money_moving = self._check_smart_money_migration(
                        source_id, target_id
                    )

                    confidence = self._compute_rotation_confidence(
                        rotation_strength, smart_money_moving
                    )

                    signals.append(CapitalRotationSignal(
                        source_cluster=source_id,
                        target_cluster=target_id,
                        rotation_strength=min(1.0, rotation_strength),
                        confidence=confidence,
                        smart_money_moving=smart_money_moving,
                    ))

        return signals

    def _check_smart_money_migration(
        self,
        source_cluster: str,
        target_cluster: str,
    ) -> bool:
        """Check if smart money is migrating between clusters."""
        # Simplified: in production, would check wallet movements
        return False

    def _compute_rotation_confidence(
        self,
        rotation_strength: float,
        smart_money_moving: bool,
    ) -> float:
        """Compute confidence for rotation signal."""
        base_confidence = min(1.0, rotation_strength * 2)
        if smart_money_moving:
            base_confidence = min(1.0, base_confidence * 1.3)
        return base_confidence

    def update_liquidity(
        self,
        cluster_id: str,
        liquidity: float,
    ) -> None:
        """Update cluster liquidity history."""
        if cluster_id not in self._cluster_liquidity:
            self._cluster_liquidity[cluster_id] = []
        self._cluster_liquidity[cluster_id].append((time.time(), liquidity))

        # Trim old entries
        self._cluster_liquidity[cluster_id] = [
            (t, v) for t, v in self._cluster_liquidity[cluster_id]
            if time.time() - t < 3600
        ]
