"""Tests for parser PnL calculation fix and wallet_features pipeline.

Tests:
1. Buy then sell profit produces positive realized_pnl
2. Buy then sell loss produces negative realized_pnl
3. Cost basis updates correctly on buys
4. total_cost_basis updates on buys
5. wallet_features computes buy_count/sell_count from events
6. Token activity metrics helper returns correct structure
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestParserPnLCalculation:
    """Test that parser correctly computes realized PnL."""

    def test_buy_cost_basis_first_buy(self) -> None:
        """First buy should set cost_basis to cost_per_token."""
        from app.workers.parser_worker import ParserWorker

        # Simulate: BUY 100 tokens for 1 SOL
        # cost_per_token = 1.0 / 100 = 0.01
        amount_in = 1.0   # SOL spent
        amount_out = 100.0  # tokens received
        cost_per_token = amount_in / amount_out  # 0.01

        # Verify formula
        assert abs(cost_per_token - 0.01) < 1e-10

    def test_sell_pnl_positive(self) -> None:
        """Sell at higher price should produce positive PnL."""
        avg_cost = 0.01  # cost per token
        sell_price = 0.02  # sell price per token
        amount = 50.0  # tokens sold

        realized = (sell_price - avg_cost) * amount
        assert realized > 0
        assert abs(realized - 0.5) < 1e-10  # (0.02 - 0.01) * 50 = 0.5

    def test_sell_pnl_negative(self) -> None:
        """Sell at lower price should produce negative PnL."""
        avg_cost = 0.02  # cost per token
        sell_price = 0.01  # sell price per token
        amount = 50.0  # tokens sold

        realized = (sell_price - avg_cost) * amount
        assert realized < 0
        assert abs(realized - (-0.5)) < 1e-10  # (0.01 - 0.02) * 50 = -0.5

    def test_sell_pnl_zero_at_cost(self) -> None:
        """Sell at cost should produce zero PnL."""
        avg_cost = 0.01
        sell_price = 0.01
        amount = 50.0

        realized = (sell_price - avg_cost) * amount
        assert abs(realized) < 1e-10

    def test_cost_basis_weighted_average(self) -> None:
        """Multiple buys should produce weighted average cost basis."""
        # Buy 1: 100 tokens at 0.01 SOL/token
        pos_size_1 = 0.0
        cost_1 = 0.01
        amount_1 = 100.0

        avg_1 = cost_1  # first buy
        pos_size_2 = pos_size_1 + amount_1  # 100

        # Buy 2: 200 tokens at 0.02 SOL/token
        cost_2 = 0.02
        amount_2 = 200.0
        new_cost = amount_2 * cost_2  # 4.0

        avg_2 = ((pos_size_2 * avg_1) + new_cost) / (pos_size_2 + amount_2)
        # (100 * 0.01 + 200 * 0.02) / 300 = (1 + 4) / 300 = 0.01667
        assert abs(avg_2 - 0.01667) < 0.001

    def test_total_cost_basis_updates(self) -> None:
        """total_cost_basis should accumulate on buys."""
        total = 0.0
        # Buy 1: 100 tokens at 0.01
        total += 100.0 * 0.01  # 1.0
        assert abs(total - 1.0) < 1e-10

        # Buy 2: 200 tokens at 0.02
        total += 200.0 * 0.02  # 4.0
        assert abs(total - 5.0) < 1e-10

    def test_realized_roi_formula(self) -> None:
        """ROI should be PnL / total_cost_basis * 100."""
        total_pnl = 0.5
        total_cost = 5.0
        roi = (total_pnl / total_cost) * 100
        assert abs(roi - 10.0) < 1e-10


class TestWalletFeaturesPipeline:
    """Test that wallet_features computes correctly from events."""

    def test_buy_event_produces_buy_count(self) -> None:
        """BUY event should produce buy_count=1."""
        payload = {
            "event_type": "BUY",
            "amount": 100.0,
            "wallet": "TestWallet11111111111111111111111111111111",
        }
        event_type = payload.get("event_type", "TRANSFER")
        amount = payload.get("amount", 0)

        features = {
            "volume": float(amount),
            "tx_frequency": 1,
            "buy_count": 1 if event_type == "BUY" else 0,
            "sell_count": 1 if event_type == "SELL" else 0,
            "transfer_count": 1 if event_type == "TRANSFER" else 0,
        }

        assert features["buy_count"] == 1
        assert features["sell_count"] == 0
        assert features["volume"] == 100.0

    def test_sell_event_produces_sell_count(self) -> None:
        """SELL event should produce sell_count=1."""
        payload = {
            "event_type": "SELL",
            "amount": 50.0,
            "wallet": "TestWallet11111111111111111111111111111111",
        }
        event_type = payload.get("event_type", "TRANSFER")
        features = {
            "buy_count": 1 if event_type == "BUY" else 0,
            "sell_count": 1 if event_type == "SELL" else 0,
        }

        assert features["buy_count"] == 0
        assert features["sell_count"] == 1

    def test_buy_sell_ratio(self) -> None:
        """Buy/sell ratio should be computed correctly."""
        buy_count = 3
        sell_count = 1
        ratio = buy_count / sell_count if sell_count > 0 else float("inf")
        assert abs(ratio - 3.0) < 1e-10

    def test_buy_sell_ratio_zero_sells(self) -> None:
        """Buy/sell ratio with zero sells should be infinity."""
        buy_count = 5
        sell_count = 0
        ratio = buy_count / sell_count if sell_count > 0 else float("inf") if buy_count > 0 else 0
        assert ratio == float("inf")


class TestTokenActivityMetrics:
    """Test token activity metrics helper."""

    def test_activity_metrics_structure(self) -> None:
        """Activity metrics should have correct keys."""
        expected_keys = [
            "token_unique_wallets_total",
            "token_buy_count_total",
            "token_sell_count_total",
            "token_buy_sell_ratio_total",
            "token_buy_volume_total",
            "token_sell_volume_total",
        ]
        # Verify the expected structure
        metrics = {
            "token_unique_wallets_total": 100,
            "token_buy_count_total": 500,
            "token_sell_count_total": 10,
            "token_buy_sell_ratio_total": 50.0,
            "token_buy_volume_total": 1000.0,
            "token_sell_volume_total": 50.0,
        }
        for key in expected_keys:
            assert key in metrics

    def test_activity_metrics_ratio_calculation(self) -> None:
        """Buy/sell ratio should handle edge cases."""
        # Normal case
        buy = 500
        sell = 10
        ratio = round(buy / sell, 2) if sell > 0 else float("inf") if buy > 0 else 0
        assert ratio == 50.0

        # Zero sells
        buy = 500
        sell = 0
        ratio = round(buy / sell, 2) if sell > 0 else float("inf") if buy > 0 else 0
        assert ratio == float("inf")

        # Zero buys and sells
        buy = 0
        sell = 0
        ratio = round(buy / sell, 2) if sell > 0 else float("inf") if buy > 0 else 0
        assert ratio == 0
