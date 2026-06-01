"""Pump prediction engine — regime-driven nonlinear amplification system.

Transformed from linear multiplier to nonlinear amplification:
- Regime exponents (1.0/1.15/1.35/1.6)
- Coherence amplification term
- Liquidity momentum boost
- Phase escalation curve
- Parabolic explosion floor
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.pump_prediction.token_flow_aggregator import TokenFlowAggregator
from app.pump_prediction.liquidity_acceleration_model import LiquidityAccelerationModel
from app.pump_prediction.cluster_convergence_detector import ClusterConvergenceDetector
from app.pump_prediction.anomaly_detector import AnomalyDetector
from app.pump_prediction.momentum_model import MomentumModel

logger = structlog.get_logger(__name__)

# Regime exponents (NONLINEAR amplification)
REGIME_EXPONENTS = {
    "NORMAL": 1.0,
    "ACCUMULATION": 1.15,
    "PUMP_BUILDUP": 1.35,
    "PARABOLIC": 1.6,
}

# Regime thresholds (CALIBRATED)
INTENSITY_THRESHOLDS = {
    "ACCUMULATION": 0.23,
    "PUMP_BUILDUP": 0.45,
    "PARABOLIC": 0.70,
}

# Burst override threshold
BURST_INTENSITY_THRESHOLD = 0.3

# Parabolic explosion floor
PARABOLIC_FLOOR = 0.65


def logistic_reshape(x: float, center: float = 0.25, sharpness: float = 8.0) -> float:
    """Logistic re-shaping for regime boundary sensitivity."""
    return 1 / (1 + math.exp(-sharpness * (x - center)))


def detect_regime_from_intensity(
    signal_intensity: float,
    burst_mode: bool = False,
    previous_regime: str = "NORMAL",
) -> str:
    """Detect regime based on signal intensity."""
    if burst_mode and signal_intensity > BURST_INTENSITY_THRESHOLD:
        return "PUMP_BUILDUP"

    if previous_regime == "PUMP_BUILDUP" and signal_intensity < 0.3:
        return "ACCUMULATION"
    elif previous_regime == "ACCUMULATION" and signal_intensity < 0.15:
        return "NORMAL"

    if signal_intensity < INTENSITY_THRESHOLDS["ACCUMULATION"]:
        return "NORMAL"
    elif signal_intensity < INTENSITY_THRESHOLDS["PUMP_BUILDUP"]:
        return "ACCUMULATION"
    elif signal_intensity < INTENSITY_THRESHOLDS["PARABOLIC"]:
        return "PUMP_BUILDUP"
    else:
        return "PARABOLIC"


def get_regime_exponent(regime: str) -> float:
    """Get regime exponent for nonlinear amplification."""
    return REGIME_EXPONENTS.get(regime, 1.0)


def compute_signal_intensity(
    signals: list[dict[str, Any]],
    cluster_density: float = 0.0,
    burst_mode: bool = False,
) -> float:
    """Compute raw signal intensity with calibration fixes."""
    if not signals:
        return 0.0

    liquidity_score = 0.0
    anomaly_score = 0.0
    momentum_score = 0.0

    for signal in signals:
        signal_type = signal.get("signal", "")
        raw_score = signal.get("score", 0.0) if signal_type != "PRE_PUMP_ANOMALY" else signal.get("anomaly_score", 0.0)
        normalized = raw_score / (raw_score + 3.0) if raw_score > 0 else 0.0

        if signal_type == "LIQUIDITY_ACCELERATION":
            liquidity_score = normalized * 1.5
        elif signal_type == "PRE_PUMP_ANOMALY":
            anomaly_score = normalized
        elif signal_type == "MOMENTUM_BUILDUP":
            momentum_score = normalized

    intensity = 0.4 * liquidity_score + 0.3 * anomaly_score + 0.3 * momentum_score
    intensity *= 1.15
    intensity = logistic_reshape(intensity, center=0.25, sharpness=8.0)

    if burst_mode:
        intensity += 0.05

    if cluster_density > 0:
        density_factor = math.log(1 + cluster_density)
        intensity *= density_factor

    return min(1.0, intensity)


def compute_coherence(signals: list[dict[str, Any]]) -> float:
    """Compute signal coherence."""
    if not signals:
        return 0.0
    product = 1.0
    for signal in signals:
        strength = signal.get("score", 0.0)
        normalized = min(1.0, strength / 2.0)
        product *= normalized
    return product


class PumpPredictionEngine:
    """Regime-driven nonlinear amplification system."""

    def __init__(self, repo: Any = None, cooldown_seconds: int = 600) -> None:
        self._repo = repo
        self._cooldown_seconds = cooldown_seconds
        self._flow_aggregator = TokenFlowAggregator()
        self._liquidity_acceleration = LiquidityAccelerationModel()
        self._cluster_convergence = ClusterConvergenceDetector()
        self._anomaly_detector = AnomalyDetector()
        self._momentum_model = MomentumModel()
        self._cooldowns: dict[str, float] = {}
        self._token_states: dict[str, dict[str, Any]] = {}
        self._regime_history: dict[str, str] = {}

    async def analyze(
        self,
        event: dict[str, Any] | list[dict[str, Any]],
        cluster_events: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any] | None:
        """Analyze event(s) for pump prediction signals."""
        events = event if isinstance(event, list) else [event]
        if not events:
            return None

        first_event = events[0]
        token = first_event.get("token", "") or first_event.get("token_in", "")
        if not token:
            return None

        # Update state
        for evt in events:
            self._update_token_state(token, evt)
            self._flow_aggregator.update(evt)

        # Update cluster activity
        if cluster_events:
            for cluster_id, cluster_wallet_events in cluster_events.items():
                if cluster_wallet_events and isinstance(cluster_wallet_events[0], dict):
                    for evt in cluster_wallet_events:
                        if isinstance(evt, dict) and evt.get("token") == token:
                            self._flow_aggregator.update_cluster(token, cluster_id)
                            break
                elif cluster_wallet_events and isinstance(cluster_wallet_events[0], str):
                    self._flow_aggregator.update_cluster(token, cluster_id)

        token_flow = self._flow_aggregator.get_token_flow(token)
        signals = self._detect_signals(token, token_flow, cluster_events or {})

        # Compute signal intensity
        cluster_density = token_flow.get("cluster_count", 0) / max(token_flow.get("wallet_count", 1), 1)
        burst_mode = token_flow.get("event_count", 0) > 20 and token_flow.get("wallet_count", 0) > 3
        signal_intensity = compute_signal_intensity(signals, cluster_density=cluster_density, burst_mode=burst_mode)

        # Detect regime
        previous_regime = self._regime_history.get(token, "NORMAL")
        regime = detect_regime_from_intensity(signal_intensity, burst_mode=burst_mode, previous_regime=previous_regime)
        self._regime_history[token] = regime

        # ── NONLINEAR AMPLIFICATION ─────────────────────────
        # Step 1: Compute base score
        base_score = self._compute_raw_score(signals)

        # Step 2: Regime exponent (amplification, not reduction)
        # For scores < 1.0, use 1 + (base * (exp - 1)) to AMPLIFY
        regime_exponent = get_regime_exponent(regime)
        if base_score < 1.0:
            score = base_score * regime_exponent
        else:
            score = base_score ** regime_exponent

        # Step 3: Coherence amplification
        coherence = compute_coherence(signals)
        score *= (1 + coherence * 0.8)

        # Step 4: Liquidity momentum boost
        liquidity_accel = 0.0
        for s in signals:
            if s.get("signal") == "LIQUIDITY_ACCELERATION":
                liquidity_accel = s.get("score", 0.0)
                break
        score *= (1 + liquidity_accel ** 1.5)

        # Step 5: Phase escalation for PUMP_BUILDUP
        if regime == "PUMP_BUILDUP":
            score *= math.exp(signal_intensity)

        # Step 6: Parabolic explosion floor
        if regime == "PARABOLIC":
            score = max(score, PARABOLIC_FLOOR)

        # Step 7: Cap at maximum
        score = min(1.0, score)

        # Conviction
        signal_density = len(signals) / 4.0
        conviction = 1 - math.exp(-2.0 * signal_density * coherence)

        # Stage and recommendation
        stage = self._get_stage(score)
        recommendation = self._get_recommendation(score, conviction)
        signal_strength = self._get_signal_strength(score)

        burst_mode = token_flow.get("event_count", 0) > 20 and token_flow.get("wallet_count", 0) > 3

        final_signal = {
            "token": token,
            "type": "PUMP_PREDICTION_SIGNAL",
            "score": round(score, 4),
            "conviction": round(conviction, 4),
            "regime": regime,
            "stage": stage,
            "signal_strength": signal_strength,
            "signals": [s.get("signal", "") for s in signals],
            "recommendation": recommendation,
            "confidence": self._calculate_confidence(signals),
            "signals_detail": signals,
            "token_flow": token_flow,
            "score_breakdown": {
                "signal_intensity": round(signal_intensity, 4),
                "base_score": round(base_score, 4),
                "regime": regime,
                "regime_exponent": regime_exponent,
                "coherence": round(coherence, 4),
                "final_score": round(score, 4),
                "burst_mode": burst_mode,
            },
            "signal_count": len(signals),
            "burst_mode": burst_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        }

        if score > 0.3 and not self._is_in_cooldown(token):
            self._cooldowns[token] = time.time()

        logger.info(
            "pump_prediction.analyzed",
            token=token[:16],
            score=round(score, 4),
            regime=regime,
            signals=[s.get("signal", "") for s in signals],
        )

        return final_signal

    def _detect_signals(self, token, token_flow, cluster_events):
        signals = []
        liquidity = self._liquidity_acceleration.detect(token, self._flow_aggregator._token_data.get(token, {}).get("events", []))
        if liquidity: signals.append(liquidity)
        cluster = self._cluster_convergence.detect(token, token_flow, cluster_events)
        if cluster: signals.append(cluster)
        token_events = self._flow_aggregator._token_data.get(token, {}).get("events", [])
        historical = self._anomaly_detector._baseline_history.get(token, [])
        anomaly = self._anomaly_detector.detect(token, token_events, historical)
        if anomaly: signals.append(anomaly)
        momentum = self._momentum_model.compute(token, token_events, token_flow)
        if momentum: signals.append(momentum)
        return signals

    def _compute_raw_score(self, signals):
        if not signals: return 0.0
        liq = clu = anom = mom = 0.0
        for s in signals:
            t = s.get("signal", "")
            raw = s.get("anomaly_score", 0.0) if t == "PRE_PUMP_ANOMALY" else s.get("score", 0.0)
            norm = raw / (raw + 3.0) if raw > 0 else 0.0
            if t == "LIQUIDITY_ACCELERATION": liq = norm
            elif t == "CLUSTER_CONVERGENCE": clu = norm
            elif t == "PRE_PUMP_ANOMALY": anom = norm
            elif t == "MOMENTUM_BUILDUP": mom = norm
        return 0.35 * liq + 0.30 * clu + 0.20 * anom + 0.15 * mom

    def _calculate_confidence(self, signals):
        if not signals: return 0.2
        confs = [s.get("confidence", 0.0) for s in signals]
        avg = sum(confs) / len(confs)
        if len(signals) >= 3: avg = min(1.0, avg * 1.2)
        elif len(signals) >= 2: avg = min(1.0, avg * 1.1)
        return avg

    def _get_stage(self, score):
        if score < 0.2: return "EARLY_STAGE"
        elif score < 0.4: return "ACCUMULATION_START"
        elif score < 0.6: return "ACCUMULATION_PHASE"
        elif score < 0.8: return "PRE_PUMP"
        else: return "HIGH_PUMP_RISK"

    def _get_recommendation(self, score, conviction):
        if conviction < 0.3: return "MONITOR"
        elif score < 0.4: return "WATCH"
        elif score < 0.7: return "WATCH_CLOSELY"
        elif score < 0.85: return "ACCUMULATE"
        else: return "ALERT"

    def _get_signal_strength(self, score):
        if score < 0.2: return "WEAK"
        elif score < 0.4: return "MODERATE"
        elif score < 0.6: return "STRONG"
        elif score < 0.8: return "VERY_STRONG"
        else: return "HIGH"

    def _update_token_state(self, token, event):
        if token not in self._token_states:
            self._token_states[token] = {"token": token, "window_5m": [], "window_15m": [], "window_1h": [], "last_updated": time.time(), "event_count": 0}
        state = self._token_states[token]
        state["event_count"] += 1
        state["last_updated"] = time.time()
        ed = {"wallet": event.get("wallet", ""), "amount": event.get("amount", 0), "event_type": event.get("event_type", ""), "timestamp": event.get("timestamp", time.time())}
        state["window_5m"].append(ed)
        state["window_15m"].append(ed)
        state["window_1h"].append(ed)
        now = time.time()
        state["window_5m"] = [e for e in state["window_5m"] if (now - e.get("timestamp", 0)) < 300]
        state["window_15m"] = [e for e in state["window_15m"] if (now - e.get("timestamp", 0)) < 900]
        state["window_1h"] = [e for e in state["window_1h"] if (now - e.get("timestamp", 0)) < 3600]

    def _is_in_cooldown(self, token):
        return (time.time() - self._cooldowns.get(token, 0)) < self._cooldown_seconds

    def get_token_state(self, token):
        return self._token_states.get(token)

    def export_states(self):
        return dict(self._token_states)
