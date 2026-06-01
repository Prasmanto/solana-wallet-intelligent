"""Smart money engine — main orchestrator for smart money detection.

Combines all signals:
- velocity_detector
- liquidity_flow_tracker
- cluster_signal_engine

Outputs unified smart money signals with scoring and recommendations.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.smart_money.signal_models import SmartMoneySignal, get_alpha_strength, get_recommendation
from app.smart_money.velocity_detector import VelocityDetector
from app.smart_money.liquidity_flow_tracker import LiquidityFlowTracker
from app.smart_money.cluster_signal_engine import ClusterSignalEngine

logger = structlog.get_logger(__name__)


class SmartMoneyEngine:
    """Main orchestrator for smart money detection.

    Combines velocity, liquidity, and cluster signals into
    unified smart money signals with scoring.
    """

    def __init__(
        self,
        repo: Any = None,
        velocity_threshold: float = 3.0,
        flow_ratio_threshold: float = 2.5,
        min_active_wallets: int = 3,
    ) -> None:
        self._repo = repo
        self._velocity = VelocityDetector(velocity_threshold=velocity_threshold)
        self._liquidity = LiquidityFlowTracker(flow_ratio_threshold=flow_ratio_threshold)
        self._cluster = ClusterSignalEngine(min_active_wallets=min_active_wallets)

        # Cooldown tracking
        self._cooldowns: dict[str, float] = {}
        self._cooldown_seconds = 600  # 10 minutes

    async def analyze(
        self,
        wallet: str,
        events: list[dict[str, Any]],
        cluster_events: dict[str, list[dict[str, Any]]] | None = None,
    ) -> SmartMoneySignal | None:
        """Analyze wallet for smart money signals.

        Args:
            wallet: Wallet address
            events: Recent events for this wallet
            cluster_events: Events for all wallets in cluster

        Returns:
            SmartMoneySignal if detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(wallet):
            return None

        signals = []

        # 1. Velocity detection
        velocity_signal = self._velocity.detect(wallet, events)
        if velocity_signal:
            signals.append(velocity_signal.to_dict())

        # 2. Liquidity flow detection
        liquidity_signal = self._liquidity.track(wallet, events)
        if liquidity_signal:
            signals.append(liquidity_signal.to_dict())

        # 3. Cluster signal detection
        if cluster_events:
            # Find wallet's cluster
            cluster_id = self._get_cluster_id(wallet, cluster_events)
            if cluster_id:
                cluster_signal = self._cluster.detect(cluster_id, cluster_events)
                if cluster_signal:
                    signals.append(cluster_signal.to_dict())

        # No signals detected
        if not signals:
            return None

        # Calculate combined score
        combined_score = self._calculate_combined_score(signals)
        alpha_strength = get_alpha_strength(combined_score)
        recommendation = get_recommendation(combined_score)

        # Get wallet type
        wallet_type = self._get_wallet_type(wallet, events)

        # Build final signal
        signal_names = [s["signal"] for s in signals]

        final_signal = SmartMoneySignal(
            entity=wallet,
            entity_type="wallet",
            signal="SMART_MONEY_ACTIVITY",
            score=combined_score,
            alpha_strength=alpha_strength,
            recommendation=recommendation,
            confidence=self._calculate_confidence(signals),
            signals=signal_names,
            metadata={
                "wallet_type": wallet_type,
                "signals_detail": signals,
                "event_count": len(events),
            },
            correlation_id=str(uuid.uuid4()),
        )

        # Set cooldown
        self._cooldowns[wallet] = time.time()

        logger.info(
            "smart_money.signal_detected",
            wallet=wallet[:16],
            score=combined_score,
            alpha_strength=alpha_strength,
            recommendation=recommendation,
            signals=signal_names,
            stage="smart_money",
        )

        return final_signal

    def _calculate_combined_score(self, signals: list[dict[str, Any]]) -> float:
        """Calculate combined score from multiple signals."""
        if not signals:
            return 0.0

        # Extract scores
        velocity_score = 0.0
        liquidity_score = 0.0
        cluster_score = 0.0

        for signal in signals:
            signal_type = signal.get("signal", "")
            score = signal.get("score", 0.0)

            if signal_type == "VELOCITY_SPIKE":
                velocity_score = score
            elif signal_type == "LIQUIDITY_ACCUMULATION":
                liquidity_score = score
            elif signal_type == "CLUSTER_ACCUMULATION":
                cluster_score = score

        # Weighted combination
        combined = (
            0.4 * velocity_score +
            0.3 * liquidity_score +
            0.3 * cluster_score
        )

        # Boost if multiple signals
        if len(signals) > 1:
            combined = min(1.0, combined * 1.2)

        return combined

    def _calculate_confidence(self, signals: list[dict[str, Any]]) -> float:
        """Calculate overall confidence from signals."""
        if not signals:
            return 0.0

        confidences = [s.get("confidence", 0.0) for s in signals]
        return sum(confidences) / len(confidences)

    def _get_wallet_type(self, wallet: str, events: list[dict[str, Any]]) -> str:
        """Get wallet type from classification."""
        # Simple heuristic based on event patterns
        tx_count = len(events)
        volume = sum(e.get("amount", 0) for e in events)

        if volume > 10000 and tx_count < 10:
            return "WHALE"
        elif tx_count > 20:
            return "BOT"
        elif volume < 100:
            return "RETAIL"
        return "UNKNOWN"

    def _is_in_cooldown(self, wallet: str) -> bool:
        """Check if wallet is in cooldown period."""
        last_signal_time = self._cooldowns.get(wallet, 0)
        return (time.time() - last_signal_time) < self._cooldown_seconds

    def _get_cluster_id(
        self,
        wallet: str,
        cluster_events: dict[str, list[dict[str, Any]]],
    ) -> str | None:
        """Get cluster ID for a wallet."""
        # Simple: use wallet as cluster ID for now
        # In production, query from DB
        return hashlib.sha256(wallet.encode()).hexdigest()[:16]
