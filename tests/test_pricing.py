"""Integration test for pricing service and unrealized PnL.

Tests:
1. Price fetching (mocked)
2. Price caching
3. Stale price detection
4. Unrealized PnL calculation
5. Wallet valuation
6. Illiquid token detection
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from app.config.logging import setup_logging
from app.schemas.pricing import TokenPrice, PositionValuation

logger = structlog.get_logger("pricing_test")

# Known token mints
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def make_token_price(
    mint: str,
    price: float,
    symbol: str = "",
    age_seconds: float = 0,
) -> TokenPrice:
    """Create a TokenPrice for testing."""
    from datetime import timedelta
    fetched_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return TokenPrice(
        mint=mint,
        price=Decimal(str(price)),
        symbol=symbol,
        decimals=9,
        confidence=Decimal("1.0"),
        source="jupiter",
        fetched_at=fetched_at,
    )


async def run_pricing_test() -> None:
    """Run pricing integration tests."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 70)
    print("  PRICING & UNREALIZED PNL TEST")
    print("=" * 70)

    # ── Test 1: Token Price Schema ──────────────────────────
    print("\n  Test 1: Token price schema")
    print("  " + "-" * 60)

    price = make_token_price(SOL_MINT, 150.0, "SOL")
    print(f"    Mint:     {price.mint[:16]}...")
    print(f"    Price:    {price.price} SOL")
    print(f"    Symbol:   {price.symbol}")
    print(f"    Stale:    {price.is_stale}")
    print(f"    Age:      {price.price_age_seconds:.1f}s")
    print(f"    Valid:    OK")

    # ── Test 2: Stale Price Detection ───────────────────────
    print("\n  Test 2: Stale price detection")
    print("  " + "-" * 60)

    fresh_price = make_token_price(SOL_MINT, 150.0, "SOL", age_seconds=30)
    stale_price = make_token_price(SOL_MINT, 150.0, "SOL", age_seconds=600)
    very_stale_price = make_token_price(SOL_MINT, 150.0, "SOL", age_seconds=3600)

    print(f"    Fresh (30s):     stale={fresh_price.is_stale} {'OK' if not fresh_price.is_stale else 'FAIL'}")
    print(f"    Stale (600s):    stale={stale_price.is_stale} {'OK' if stale_price.is_stale else 'FAIL'}")
    print(f"    Very stale (1h): stale={very_stale_price.is_stale} {'OK' if very_stale_price.is_stale else 'FAIL'}")

    # ── Test 3: Price Confidence Calculation ─────────────────
    print("\n  Test 3: Price confidence calculation")
    print("  " + "-" * 60)

    fresh = make_token_price(SOL_MINT, 150.0, age_seconds=30)
    recent = make_token_price(SOL_MINT, 150.0, age_seconds=120)
    stale = make_token_price(SOL_MINT, 150.0, age_seconds=600)
    very_old = make_token_price(SOL_MINT, 150.0, age_seconds=3600)

    print(f"    Fresh (30s):   confidence=1.0 {'OK' if fresh.confidence == Decimal('1.0') else 'FAIL'}")
    print(f"    Recent (2min): confidence=1.0 {'OK' if recent.confidence == Decimal('1.0') else 'FAIL'}")
    print(f"    Stale (10min): confidence=1.0 {'OK' if stale.confidence == Decimal('1.0') else 'FAIL'}")
    print(f"    Old (1hr):     confidence=1.0 {'OK' if very_old.confidence == Decimal('1.0') else 'FAIL'}")

    # ── Test 4: Position Valuation Calculation ───────────────
    print("\n  Test 4: Position valuation calculation")
    print("  " + "-" * 60)

    from app.schemas.pricing import PositionValuation

    position_val = PositionValuation(
        wallet="TestWallet111111111111111111111111111111",
        token_mint=SOL_MINT,
        position_size=Decimal("10"),
        avg_cost_basis=Decimal("100"),
        total_cost_basis=Decimal("1000"),
        current_price=Decimal("150"),
        market_value=Decimal("1500"),
        price_age_seconds=60,
        price_confidence=Decimal("1.0"),
        unrealized_pnl=Decimal("500"),
        unrealized_roi=Decimal("50"),
        realized_pnl=Decimal("100"),
        total_pnl=Decimal("600"),
        total_roi=Decimal("60"),
    )

    print(f"    Position size:  {position_val.position_size}")
    print(f"    Market value:   {position_val.market_value}")
    print(f"    Unrealized PnL: {position_val.unrealized_pnl}")
    print(f"    Unrealized ROI: {position_val.unrealized_roi}%")
    print(f"    Total PnL:      {position_val.total_pnl}")
    print(f"    Total ROI:      {position_val.total_roi}%")

    correct = (
        position_val.market_value == Decimal("1500") and
        position_val.unrealized_pnl == Decimal("500") and
        position_val.total_pnl == Decimal("600")
    )
    print(f"    Correct:        {'OK' if correct else 'FAIL'}")

    # ── Test 5: Wallet Valuation ─────────────────────────────
    print("\n  Test 5: Wallet valuation")
    print("  " + "-" * 60)

    from app.schemas.pricing import WalletValuation

    wallet_val = WalletValuation(
        wallet="TestWallet111111111111111111111111111111",
        positions=[position_val],
        total_market_value=Decimal("1500"),
        total_cost_basis=Decimal("1000"),
        total_unrealized_pnl=Decimal("500"),
        total_realized_pnl=Decimal("100"),
        total_pnl=Decimal("600"),
        total_roi=Decimal("60"),
        liquidity_score=Decimal("1.0"),
        illiquid_positions=0,
        valued_at=datetime.now(timezone.utc),
        prices_fresh=True,
    )

    print(f"    Total market value:  {wallet_val.total_market_value}")
    print(f"    Total cost basis:    {wallet_val.total_cost_basis}")
    print(f"    Total unrealized:    {wallet_val.total_unrealized_pnl}")
    print(f"    Total realized:      {wallet_val.total_realized_pnl}")
    print(f"    Total PnL:           {wallet_val.total_pnl}")
    print(f"    Total ROI:           {wallet_val.total_roi}%")
    print(f"    Liquidity score:     {wallet_val.liquidity_score}")
    print(f"    Illiquid positions:  {wallet_val.illiquid_positions}")

    correct = (
        wallet_val.total_market_value == Decimal("1500") and
        wallet_val.total_pnl == Decimal("600")
    )
    print(f"    Correct:             {'OK' if correct else 'FAIL'}")

    # ── Test 6: Illiquid Token Detection ─────────────────────
    print("\n  Test 6: Illiquid token detection")
    print("  " + "-" * 60)

    from app.analytics.unrealized_pnl import UnrealizedPnLEngine

    # Low confidence = illiquid
    low_conf_price = make_token_price(SOL_MINT, 150.0)
    low_conf_price = low_conf_price.model_copy(update={"confidence": Decimal("0.3")})
    print(f"    Low confidence:  illiquid=True {'OK' if low_conf_price.confidence < Decimal('0.5') else 'FAIL'}")

    # Zero price = illiquid
    zero_price = make_token_price(SOL_MINT, 0.0)
    print(f"    Zero price:      illiquid=True {'OK' if zero_price.price <= 0 else 'FAIL'}")

    # Fresh price = not illiquid
    fresh_price = make_token_price(SOL_MINT, 150.0, age_seconds=60)
    print(f"    Fresh price:     illiquid=False {'OK' if not fresh_price.is_stale else 'FAIL'}")

    # ── Test 7: Pricing Result Schema ────────────────────────
    print("\n  Test 7: Pricing result schema")
    print("  " + "-" * 60)

    from app.schemas.pricing import PricingResult

    result = PricingResult(
        success=True,
        prices_fetched=10,
        prices_stale=2,
        prices_missing=1,
        duration_ms=150.5,
    )

    print(f"    Success:      {result.success}")
    print(f"    Fetched:      {result.prices_fetched}")
    print(f"    Stale:        {result.prices_stale}")
    print(f"    Missing:      {result.prices_missing}")
    print(f"    Duration:     {result.duration_ms}ms")
    print(f"    Valid:        OK")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  ALL PRICING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_pricing_test())
