"""Token ranking engine — vector-based with local market features and lead-lag detection.

Upgraded with:
- Local market features (per-token)
- Multi-timeframe decomposition
- Lead-lag detection
- Regime decoupling per token
- Anti-smoothing corrections
- Identity residual path
"""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine
from app.pump_prediction.lead_lag_detector import LeadLagDetector
from app.pump_prediction.local_market_features import LocalMarketFeatures

logger = structlog.get_logger(__name__)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x ** 2 for x in a))
    norm_b = math.sqrt(sum(x ** 2 for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def sigmoid_attention(features: list[float], scale: float = 2.0) -> list[float]:
    """Sigmoid attention (prevents softmax collapse)."""
    return [sigmoid(f * scale) for f in features]


FEATURE_NAMES = ["liquidity", "momentum", "cluster", "smart_money", "velocity", "anomaly"]


@dataclass
class TokenAlphaScore:
    """Alpha score for a single token."""

    token: str
    alpha_score: float
    regime: str
    is_leader: bool
    lead_strength_score: float
    smart_money_flag: bool
    local_momentum_state: str
    market_vector: list[float]
    identity_vector: list[float]
    final_vector: list[float]
    attention_weights: list[float]
    signals: dict[str, float]
    local_features: dict[str, dict[str, float]]
    contrastive_penalty: float
    confidence: float
    timestamp: str
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "alpha_score": round(self.alpha_score, 4),
            "regime": self.regime,
            "is_leader": self.is_leader,
            "lead_strength_score": round(self.lead_strength_score, 4),
            "smart_money_flag": self.smart_money_flag,
            "local_momentum_state": self.local_momentum_state,
            "market_vector": [round(v, 4) for v in self.market_vector],
            "attention_weights": [round(v, 4) for v in self.attention_weights],
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
            "event_count": self.event_count,
        }


FEATURE_DIMS = ["liquidity", "momentum", "cluster", "smart_money", "velocity", "anomaly"]


class TokenRankingEngine:
    """Vector-based ranking with local market features and lead-lag detection."""

    def __init__(self, pump_engine: PumpPredictionEngine | None = None) -> None:
        self._pump_engine = pump_engine or PumpPredictionEngine()
        self._lead_lag = LeadLagDetector()
        self._local_features = LocalMarketFeatures()
        self._token_data: dict[str, list[dict[str, Any]]] = {}
        self._last_ranking: list[TokenAlphaScore] = []
        self._token_vectors: dict[str, list[float]] = {}
        self._previous_vectors: dict[str, list[float]] = {}
        self._global_intensity: float = 0.0

    async def update(self, event: dict[str, Any]) -> None:
        """Update token data with new event."""
        token = event.get("token", "") or event.get("token_in", "")
        if not token:
            return
        if token not in self._token_data:
            self._token_data[token] = []
        self._token_data[token].append(event)
        if len(self._token_data[token]) > 1000:
            self._token_data[token] = self._token_data[token][-1000:]

    async def rank_tokens(
        self,
        cluster_events: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[TokenAlphaScore]:
        """Rank all tokens with local market features and lead-lag detection."""
        rankings = []

        # Compute global average intensity for regime decoupling
        self._global_intensity = self._compute_global_intensity()

        for token, events in self._token_data.items():
            if not events:
                continue

            pump_signal = await self._pump_engine.analyze(events, cluster_events)
            alpha_score = self._compute_alpha_score(token, events, pump_signal, cluster_events or {})
            rankings.append(alpha_score)
            self._token_vectors[token] = alpha_score.final_vector

        # Apply contrastive penalty
        for ranking in rankings:
            penalty = self._compute_contrastive_penalty(ranking.token)
            ranking.contrastive_penalty = penalty
            ranking.alpha_score *= (1 - penalty)

        # Apply competition normalization
        rankings = self._apply_competition(rankings)

        # Sort
        rankings.sort(key=lambda x: x.alpha_score, reverse=True)

        self._last_ranking = rankings
        return rankings

    def _compute_global_intensity(self) -> float:
        """Compute global average intensity."""
        if not self._token_data:
            return 0.0

        intensities = []
        for token, events in self._token_data.items():
            if events:
                volume = sum(e.get("amount", 0) for e in events)
                intensity = min(1.0, volume / 5000)
                intensities.append(intensity)

        return sum(intensities) / len(intensities) if intensities else 0.0

    def _compute_alpha_score(
        self,
        token: str,
        events: list[dict[str, Any]],
        pump_signal: dict[str, Any] | None,
        cluster_events: dict[str, list[dict[str, Any]]],
    ) -> TokenAlphaScore:
        """Compute alpha score with all upgrades."""
        # Market vector (global features)
        market_vector = self._compute_market_vector(events)

        # Local market features
        local_features = self._local_features.compute_local_features(token, events)

        # Identity vector
        identity_vector = self._compute_identity_vector(token, events)

        # Residual merge
        alpha = 0.3
        final_vector = [m + i * alpha for m, i in zip(market_vector, identity_vector)]

        # Sigmoid attention
        attention_weights = sigmoid_attention(market_vector)

        # Base score from attention-weighted features
        base_score = sum(w * v for w, v in zip(attention_weights, market_vector))

        # Regime decoupling (per-token)
        token_regime = self._get_token_regime(events, pump_signal)

        # Regime multiplier
        regime_mult = self._get_regime_multiplier(token_regime)
        base_score *= regime_mult

        # Smart money boost
        smart_money_boost = self._compute_smart_money_boost(events)
        base_score *= (1 + smart_money_boost)

        # Cluster boost
        cluster_boost = self._compute_cluster_boost(events)
        base_score *= (1 + cluster_boost)

        # Anti-smoothing: variance boost
        variance = self._compute_variance(market_vector)
        base_score += variance * 0.2

        # Decorrelation penalty
        cluster_mean = self._get_cluster_mean(cluster_events)
        penalty = cosine_similarity(market_vector, cluster_mean) * 0.15
        base_score -= penalty

        # Anti-noise
        if base_score < 0.15:
            base_score = 0.0

        # Cap
        base_score = min(1.0, base_score)

        # Build signals
        signals = dict(zip(FEATURE_DIMS, market_vector))

        # Determine leader
        lead_info = self._lead_lag.detect_leaders(
            list(self._token_data.keys()),
            self._token_data,
        )
        is_leader = lead_info.get("leader_token") == token
        lead_strength = lead_info.get("lead_scores", {}).get(token, 0.0)

        # Smart money flag
        smart_money_flag = smart_money_boost > 0

        # Local momentum state
        local_momentum = local_features.get("mid_term", {}).get("velocity", 0.0)
        momentum_state = "accelerating" if local_momentum > 0.5 else "stable" if local_momentum > 0.2 else "decelerating"

        confidence = pump_signal.get("confidence", 0.0) if pump_signal else 0.0

        return TokenAlphaScore(
            token=token,
            alpha_score=base_score,
            regime=token_regime,
            is_leader=is_leader,
            lead_strength_score=lead_strength,
            smart_money_flag=smart_money_flag,
            local_momentum_state=momentum_state,
            market_vector=market_vector,
            identity_vector=identity_vector,
            final_vector=final_vector,
            attention_weights=attention_weights,
            signals=signals,
            local_features=local_features,
            contrastive_penalty=0.0,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_count=len(events),
        )

    def _get_token_regime(
        self,
        events: list[dict[str, Any]],
        pump_signal: dict[str, Any] | None,
    ) -> str:
        """Get token-specific regime (decoupled from global)."""
        global_regime = pump_signal.get("regime", "NORMAL") if pump_signal else "NORMAL"

        # Compute local intensity
        local_intensity = self._compute_local_intensity(events)

        # Token regime bias (decoupling)
        token_regime_bias = local_intensity - self._global_intensity

        # Adjust regime based on bias
        if token_regime_bias > 0.2:
            # Token is ahead of global → more bullish
            if global_regime == "NORMAL":
                return "ACCUMULATION"
            elif global_regime == "ACCUMULATION":
                return "PUMP_BUILDUP"
        elif token_regime_bias < -0.2:
            # Token is behind global → less bullish
            if global_regime == "PUMP_BUILDUP":
                return "ACCUMULATION"
            elif global_regime == "ACCUMULATION":
                return "NORMAL"

        return global_regime

    def _compute_local_intensity(self, events: list[dict[str, Any]]) -> float:
        """Compute local token intensity."""
        if not events:
            return 0.0

        # Recent volume
        now = events[-1].get("timestamp", time.time()) if events else time.time()
        recent = [e for e in events if (now - e.get("timestamp", 0)) < 300]
        volume = sum(e.get("amount", 0) for e in recent)

        return min(1.0, volume / 3000)

    def _compute_global_intensity(self) -> float:
        """Compute global average intensity."""
        if not self._token_data:
            return 0.0

        intensities = []
        for token, events in self._token_data.items():
            if events:
                volume = sum(e.get("amount", 0) for e in events)
                intensity = min(1.0, volume / 5000)
                intensities.append(intensity)

        return sum(intensities) / len(intensities) if intensities else 0.0

    def _compute_market_vector(self, events: list[dict[str, Any]]) -> list[float]:
        """Compute market dynamics vector."""
        return [
            self._compute_liquidity(events),
            self._compute_momentum(events),
            self._compute_cluster(events),
            self._compute_smart_money(events),
            self._compute_velocity(events),
            self._compute_anomaly(events),
        ]

    def _compute_identity_vector(self, token: str, events: list[dict[str, Any]]) -> list[float]:
        """Compute token identity embedding."""
        hash_bytes = hashlib.sha256(token.encode()).digest()
        vector = [(hash_bytes[i % len(hash_bytes)] / 127.5) - 1.0 for i in range(6)]

        if events:
            volume = sum(e.get("amount", 0) for e in events)
            tx_count = len(events)
            vector[0] += min(1.0, volume / 10000)
            vector[1] += min(1.0, tx_count / 100)

        return vector

    def _compute_variance(self, vector: list[float]) -> float:
        """Compute variance of feature vector."""
        if not vector:
            return 0.0
        mean = sum(vector) / len(vector)
        variance = sum((x - mean) ** 2 for x in vector) / len(vector)
        return min(1.0, variance)

    def _get_cluster_mean(self, cluster_events: dict[str, list[dict[str, Any]]]) -> list[float]:
        """Get mean feature vector for cluster."""
        if not cluster_events:
            return [0.0] * 6

        all_vectors = []
        for token, events in cluster_events.items():
            if events:
                vec = self._compute_market_vector(events)
                all_vectors.append(vec)

        if not all_vectors:
            return [0.0] * 6

        # Element-wise mean
        mean = [0.0] * 6
        for vec in all_vectors:
            for i in range(6):
                mean[i] += vec[i]
        mean = [v / len(all_vectors) for v in mean]

        return mean

    def _compute_contrastive_penalty(self, token: str) -> float:
        """Compute contrastive penalty to prevent identical rankings."""
        if token not in self._token_vectors or len(self._token_vectors) < 2:
            return 0.0

        token_vec = self._token_vectors[token]
        similarities = []

        for other_token, other_vec in self._token_vectors.items():
            if other_token == token:
                continue
            sim = cosine_similarity(token_vec, other_vec)
            similarities.append(sim)

        if not similarities:
            return 0.0

        avg_similarity = sum(similarities) / len(similarities)
        return avg_similarity * 0.15

    def _compute_liquidity(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        buys = sum(1 for e in events if e.get("event_type") == "BUY")
        total = len(events)
        return min(1.0, buys / total) if total > 0 else 0.0

    def _compute_momentum(self, events: list[dict[str, Any]]) -> float:
        if len(events) < 2: return 0.0
        timestamps = [e.get("timestamp", 0) for e in events]
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        if avg_interval < 60: return 0.9
        elif avg_interval < 300: return 0.7
        elif avg_interval < 900: return 0.5
        return 0.2

    def _compute_cluster(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        wallets = set(e.get("wallet", "") for e in events if e.get("wallet"))
        unique = len(wallets)
        if unique >= 5: return 0.9
        elif unique >= 3: return 0.7
        elif unique >= 2: return 0.5
        return 0.2

    def _compute_smart_money(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        volume = sum(e.get("amount", 0) for e in events)
        tx_count = len(events)
        if tx_count == 0: return 0.0
        avg_volume = volume / tx_count
        if avg_volume > 500 and tx_count < 20: return 0.8
        elif avg_volume > 200: return 0.5
        return 0.2

    def _compute_velocity(self, events: list[dict[str, Any]]) -> float:
        if len(events) < 2: return 0.0
        timestamps = [e.get("timestamp", 0) for e in events]
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        if avg_interval < 60: return 0.9
        elif avg_interval < 300: return 0.7
        elif avg_interval < 900: return 0.5
        return 0.2

    def _compute_anomaly(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        volume = sum(e.get("amount", 0) for e in events)
        if volume > 10000: return 0.9
        elif volume > 5000: return 0.7
        elif volume > 1000: return 0.4
        return 0.1

    def _get_regime_multiplier(self, regime: str) -> float:
        return {"NORMAL": 1.0, "ACCUMULATION": 1.15, "PUMP_BUILDUP": 1.35, "PARABOLIC": 1.6}.get(regime, 1.0)

    def _compute_smart_money_boost(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        volume = sum(e.get("amount", 0) for e in events)
        wallets = set(e.get("wallet", "") for e in events if e.get("wallet"))
        if volume > 5000 and len(wallets) <= 3: return 0.4
        elif volume > 2000: return 0.2
        return 0.0

    def _compute_cluster_boost(self, events: list[dict[str, Any]]) -> float:
        if not events: return 0.0
        wallets = set(e.get("wallet", "") for e in events if e.get("wallet"))
        unique = len(wallets)
        if unique >= 5: return 0.3
        elif unique >= 3: return 0.15
        return 0.0

    def _apply_competition(self, rankings: list[TokenAlphaScore]) -> list[TokenAlphaScore]:
        if len(rankings) <= 1: return rankings
        all_scores = [r.alpha_score for r in rankings]
        total = sum(all_scores)
        if total == 0: return rankings
        for r in rankings:
            r.alpha_score *= r.alpha_score / total
        return rankings

    def get_rankings(self) -> list[TokenAlphaScore]:
        return self._last_ranking

    def get_token_alpha(self, token: str) -> TokenAlphaScore | None:
        for r in self._last_ranking:
            if r.token == token: return r
        return None
