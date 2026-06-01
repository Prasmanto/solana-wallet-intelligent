"""Wallet classifier — classifies wallets based on behavioral features.

Classification rules:
- SNIPER: first interaction within token launch window, high win ratio
- WHALE: large transfer volume, low frequency, high size
- BOT: high frequency regular interval, repeated pattern transfers
- RETAIL: random low frequency behavior
- UNKNOWN: insufficient data
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class WalletClassifier:
    """Classifies wallets based on behavioral features."""

    def classify(self, wallet: str, features: dict[str, Any]) -> dict[str, Any]:
        """Classify a wallet based on extracted features.

        Args:
            wallet: Wallet address
            features: Computed features from PersistentFeatureStore

        Returns:
            Wallet classification with type and confidence
        """
        if not features or features.get("tx_frequency", 0) == 0:
            return {
                "wallet": wallet,
                "wallet_type": "UNKNOWN",
                "confidence": 0.0,
                "reason": "no_events",
            }

        # Classify based on features
        wallet_type, confidence, reason = self._classify_by_features(features)

        return {
            "wallet": wallet,
            "wallet_type": wallet_type,
            "confidence": confidence,
            "reason": reason,
        }

    def _classify_by_features(
        self,
        features: dict[str, Any],
    ) -> tuple[str, float, str]:
        """Classify wallet based on extracted features."""
        tx_frequency = features.get("tx_frequency", 0)
        avg_interval = features.get("avg_interval", float("inf"))
        token_diversity = features.get("token_diversity", 0)
        volume = features.get("volume", 0)
        buy_sell_ratio = features.get("buy_sell_ratio", 0)

        # WHALE: large volume, low frequency
        if volume > 10000 and tx_frequency < 10:
            return "WHALE", 0.85, "high_volume_low_frequency"

        # SNIPER: high frequency, recent activity
        if tx_frequency > 20 and avg_interval < 60:
            return "SNIPER", 0.8, "high_frequency_recent"

        # BOT: high frequency, regular intervals, low diversity
        if tx_frequency > 15 and avg_interval < 120 and token_diversity < 5:
            return "BOT", 0.75, "regular_pattern"

        # RETAIL: low frequency, random behavior
        if tx_frequency < 10 and token_diversity < 3:
            return "RETAIL", 0.6, "low_frequency_random"

        # Default
        return "UNKNOWN", 0.3, "insufficient_data"

    def classify_batch(
        self,
        wallet_features: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify multiple wallets."""
        results = []
        for wallet, features in wallet_features.items():
            result = self.classify(wallet, features)
            results.append(result)
        return results
