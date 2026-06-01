"""Cluster forecaster — forecasts future dominant clusters."""

from __future__ import annotations

from typing import Any

import structlog

from app.forecasting.forecast_models import ClusterForecast
from app.forecasting.cluster_energy_model import ClusterEnergyModel

logger = structlog.get_logger(__name__)


class ClusterForecaster:
    """Forecasts future dominant clusters."""

    def __init__(self, energy_model: ClusterEnergyModel) -> None:
        self._energy_model = energy_model

    def forecast_clusters(
        self,
        cluster_energies: dict[str, float],
        rotation_signals: list[dict[str, Any]],
        time_horizons: list[int] = None,
    ) -> list[ClusterForecast]:
        """Forecast future dominant clusters.

        Args:
            cluster_energies: Current energy scores per cluster
            rotation_signals: Capital rotation signals
            time_horizons: Forecast horizons in minutes [15, 60, 240]
        """
        if time_horizons is None:
            time_horizons = [15, 60, 240]

        forecasts = []

        for cluster_id, energy in cluster_energies.items():
            for horizon in time_horizons:
                forecast = self._forecast_single(
                    cluster_id, energy, rotation_signals, horizon
                )
                forecasts.append(forecast)

        # Sort by forecast_score descending
        forecasts.sort(key=lambda x: x.forecast_score, reverse=True)

        return forecasts

    def _forecast_single(
        self,
        cluster_id: str,
        current_energy: float,
        rotation_signals: list[dict[str, Any]],
        horizon_minutes: int,
    ) -> ClusterForecast:
        """Forecast a single cluster's future state."""
        # Base forecast from current energy
        base_forecast = current_energy

        # Adjust for capital rotation
        rotation_boost = 0.0
        for rotation in rotation_signals:
            if rotation.get("target_cluster") == cluster_id:
                rotation_boost += rotation.get("rotation_strength", 0) * 0.3
            elif rotation.get("source_cluster") == cluster_id:
                rotation_boost -= rotation.get("rotation_strength", 0) * 0.2

        # Apply time decay (longer horizon = more decay)
        time_decay = 1.0 / (1 + horizon_minutes * 0.01)

        # Compute forecast score
        forecast_score = (base_forecast + rotation_boost) * time_decay
        forecast_score = max(0.0, min(1.0, forecast_score))

        # Compute confidence
        confidence = self._compute_forecast_confidence(
            current_energy, rotation_boost, horizon_minutes
        )

        # Determine contributing factors
        factors = []
        if rotation_boost > 0:
            factors.append("capital_inflow")
        elif rotation_boost < 0:
            factors.append("capital_outflow")
        if current_energy > 0.7:
            factors.append("high_energy")

        return ClusterForecast(
            cluster_id=cluster_id,
            forecast_score=forecast_score,
            confidence=confidence,
            expected_time_horizon=f"{horizon_minutes}m",
            contributing_factors=factors,
        )

    def _compute_forecast_confidence(
        self,
        energy: float,
        rotation: float,
        horizon: int,
    ) -> float:
        """Compute forecast confidence."""
        # Higher energy and shorter horizon = higher confidence
        energy_factor = min(1.0, energy)
        horizon_factor = max(0.3, 1.0 - horizon * 0.002)
        rotation_factor = min(1.0, abs(rotation) + 0.5)

        return energy_factor * horizon_factor * rotation_factor

    def get_top_forecasts(
        self,
        forecasts: list[ClusterForecast],
        top_n: int = 3,
    ) -> list[ClusterForecast]:
        """Get top N forecasted clusters."""
        sorted_forecasts = sorted(
            forecasts, key=lambda x: x.forecast_score, reverse=True
        )
        return sorted_forecasts[:top_n]
