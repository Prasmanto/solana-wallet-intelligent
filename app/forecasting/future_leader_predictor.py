"""Future leader predictor — predicts next leader before current leader weakens."""

from __future__ import annotations

from typing import Any

import structlog

from app.forecasting.forecast_models import FutureLeaderPrediction

logger = structlog.get_logger(__name__)


class FutureLeaderPredictor:
    """Predicts next leader token before current leader weakens."""

    def __init__(self) -> None:
        self._token_momentum: dict[str, list[float]] = {}
        self._leader_history: list[tuple[str, float]] = []

    def predict_leader(
        self,
        token_rankings: list[dict[str, Any]],
        cluster_energy: dict[str, float],
        lead_lag_data: dict[str, Any],
    ) -> FutureLeaderPrediction:
        """Predict next leader token.

        Algorithm:
        1. Identify current leader (highest rank)
        2. Find emerging tokens (momentum increasing)
        3. Compute transition probability
        4. Estimate ETA
        """
        if not token_rankings:
            return FutureLeaderPrediction(
                current_leader="",
                predicted_next_leader="",
                probability=0.0,
                eta_minutes=0,
                emerging_tokens=[],
                fading_tokens=[],
                cluster_id="",
            )

        # Sort by alpha_score
        sorted_tokens = sorted(
            token_rankings, key=lambda x: x.get("alpha_score", 0), reverse=True
        )

        current_leader = sorted_tokens[0].get("token", "") if sorted_tokens else ""

        # Identify emerging and fading tokens
        emerging = []
        fading = []

        for token_data in sorted_tokens:
            token = token_data.get("token", "")
            momentum = token_data.get("local_momentum_state", "")
            smart_money = token_data.get("smart_money_flag", False)

            # Emerging: high momentum or smart money activity
            if momentum == "accelerating" or smart_money:
                emerging.append(token)

            # Fading: low momentum and not smart money
            if momentum == "decelerating" and not smart_money:
                fading.append(token)

        # Predict next leader
        predicted_leader = self._predict_next_leader(
            current_leader, emerging, fading, sorted_tokens
        )

        # Compute probability
        probability = self._compute_transition_probability(
            current_leader, predicted_leader, emerging, fading
        )

        # Estimate ETA
        eta = self._estimate_eta(emerging, fading)

        # Get cluster ID
        cluster_id = sorted_tokens[0].get("cluster_id", "") if sorted_tokens else ""

        return FutureLeaderPrediction(
            current_leader=current_leader,
            predicted_next_leader=predicted_leader,
            probability=probability,
            eta_minutes=eta,
            emerging_tokens=emerging[:5],
            fading_tokens=fading[:5],
            cluster_id=cluster_id,
        )

    def _predict_next_leader(
        self,
        current_leader: str,
        emerging: list[str],
        fading: list[str],
        sorted_tokens: list[dict[str, Any]],
    ) -> str:
        """Predict next leader token."""
        # If current leader is fading, pick top emerging token
        if current_leader in fading and emerging:
            return emerging[0]

        # Otherwise, pick second-highest ranked token
        if len(sorted_tokens) > 1:
            return sorted_tokens[1].get("token", "")

        return current_leader

    def _compute_transition_probability(
        self,
        current_leader: str,
        predicted_leader: str,
        emerging: list[str],
        fading: list[str],
    ) -> float:
        """Compute probability of leadership transition."""
        if current_leader == predicted_leader:
            return 0.3  # Low probability of staying leader

        # Higher probability if current leader is fading
        if current_leader in fading:
            base_prob = 0.7
        else:
            base_prob = 0.4

        # Boost if predicted leader is emerging
        if predicted_leader in emerging:
            base_prob += 0.2

        return min(0.95, base_prob)

    def _estimate_eta(
        self,
        emerging: list[str],
        fading: list[str],
    ) -> int:
        """Estimate minutes until leadership transition."""
        # More emerging tokens = faster transition
        if not emerging:
            return 60  # Default: 1 hour
        elif len(emerging) >= 3:
            return 15  # Fast transition
        elif len(emerging) >= 2:
            return 30
        else:
            return 45
