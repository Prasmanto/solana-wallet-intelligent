"""Cluster energy model — estimates stored momentum in clusters.

Computes cluster_energy_score (0-1) based on:
- smart money activity
- cluster size
- cluster density
- wallet reuse frequency
- liquidity accumulation
- momentum acceleration
- exponential decay over time
"""

from __future__ import annotations

import math
import time
from typing import Any

import structlog

from app.forecasting.forecast_models import ClusterEnergySnapshot

logger = structlog.get_logger(__name__)

# Decay constant (higher = faster decay)
DECAY_LAMBDA = 0.01


class ClusterEnergyModel:
    """Estimates stored momentum inside a cluster."""

    def __init__(self) -> None:
        self._cluster_energy: dict[str, float] = {}
        self._cluster_history: dict[str, list[tuple[float, float]]] = {}

    def compute_energy(
        self,
        cluster_id: str,
        cluster_data: dict[str, Any],
    ) -> ClusterEnergySnapshot:
        """Compute energy score for a cluster.

        Energy accumulates when:
        - liquidity grows
        - smart money accumulates
        - cluster density increases
        - velocity accelerates

        Energy decays exponentially if activity disappears.
        """
        # Extract inputs
        smart_money_density = cluster_data.get("smart_money_density", 0.0)
        cluster_size = cluster_data.get("cluster_size", 0)
        cluster_density = cluster_data.get("cluster_density", 0.0)
        liquidity_pressure = cluster_data.get("liquidity_pressure", 0.0)
        momentum_score = cluster_data.get("momentum_score", 0.0)
        wallet_reuse = cluster_data.get("wallet_reuse", 0.0)

        # Compute energy components
        components = {
            "smart_money": min(1.0, smart_money_density * 0.3),
            "size": min(1.0, cluster_size / 10),
            "density": min(1.0, cluster_density * 0.25),
            "liquidity": min(1.0, liquidity_pressure * 0.2),
            "momentum": min(1.0, momentum_score * 0.15),
            "reuse": min(1.0, wallet_reuse * 0.1),
        }

        # Weighted sum
        raw_energy = sum(components.values())

        # Apply exponential decay based on time since last activity
        last_activity = cluster_data.get("last_activity", time.time())
        time_since_activity = time.time() - last_activity
        decay = math.exp(-DECAY_LAMBDA * time_since_activity)

        # Apply decay
        energy_score = raw_energy * decay

        # Compute trend
        prev_energy = self._cluster_energy.get(cluster_id, 0.0)
        if energy_score > prev_energy * 1.1:
            trend = "rising"
        elif energy_score < prev_energy * 0.9:
            trend = "decaying"
        else:
            trend = "stable"

        # Update stored energy
        self._cluster_energy[cluster_id] = energy_score

        # Store history
        if cluster_id not in self._cluster_history:
            self._cluster_history[cluster_id] = []
        self._cluster_history[cluster_id].append((time.time(), energy_score))

        # Trim history (keep last 100 points)
        if len(self._cluster_history[cluster_id]) > 100:
            self._cluster_history[cluster_id] = self._cluster_history[cluster_id][-100:]

        return ClusterEnergySnapshot(
            cluster_id=cluster_id,
            energy_score=min(1.0, energy_score),
            trend=trend,
            smart_money_density=smart_money_density,
            liquidity_pressure=liquidity_pressure,
            momentum_score=momentum_score,
        )

    def get_energy_history(self, cluster_id: str) -> list[tuple[float, float]]:
        """Get energy history for a cluster."""
        return self._cluster_history.get(cluster_id, [])

    def get_all_energies(self) -> dict[str, float]:
        """Get current energy scores for all clusters."""
        return dict(self._cluster_energy)
