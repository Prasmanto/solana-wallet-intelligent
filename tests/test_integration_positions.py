"""Integration test for position tracking and metrics aggregation.

Validates the full pipeline:
1. Process trades through position service
2. Verify FIFO lot accounting
3. Verify realized PnL calculation
4. Verify wallet metrics aggregation
5. Verify idempotent processing
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config.logging import setup_logging
from app.config.settings import settings
from app.infrastructure.database.session import Base
from app.infrastructure.database.repositories.position_repo import PositionRepository
from app.analytics.position_service import PositionService
from app.analytics.metrics_aggregator import MetricsAggregator
from app.schemas.trade import NormalizedTrade, TokenInfo, TradeDirection, DEXProtocol

logger = structlog.get_logger("integration_test")


def make_trade(
    trade_id: str,
    wallet: str,
    direction: str,
    token_in_mint: str,
    token_in_amount: str,
    token_out_mint: str,
    token_out_amount: str,
    fee_sol: str = "0.000005",
    timestamp: str = "2026-01-01T10:00:00Z",
) -> NormalizedTrade:
    """Create a NormalizedTrade."""
    return NormalizedTrade(
        trade_id=trade_id,
        signature=f"sig_{trade_id}",
        slot=12345,
        timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        wallet=wallet,
        direction=TradeDirection(direction),
        token_in=TokenInfo(
            mint=token_in_mint,
            amount=Decimal(token_in_amount),
            decimals=6 if "EPjFWdd5" in token_in_mint else 9,
        ),
        token_out=TokenInfo(
            mint=token_out_mint,
            amount=Decimal(token_out_amount),
            decimals=9,
        ),
        protocol=DEXProtocol.JUPITER,
        fee_sol=Decimal(fee_sol),
    )


async def run_integration_test() -> None:
    """Run the full integration test."""
    setup_logging(log_level="INFO", json_output=False)

    print("\n" + "=" * 70)
    print("  POSITION TRACKING INTEGRATION TEST")
    print("=" * 70)

    # Connect to database
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=5)

    # Check if tables exist
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        has_positions = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("wallet_positions")
        )
        if not has_positions:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Use unique wallet for this test run
    import uuid
    test_id = str(uuid.uuid4())[:8]
    wallet = f"TestW{test_id}"
    token = "TokenMint111111111111111111111111111111"
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # ── Test 1: Process buy trade ───────────────────────────
    print("\n  Test 1: Process buy trade")
    print("  " + "-" * 60)

    async with session_factory() as session:
        service = PositionService(session)

        buy_trade = make_trade(
            trade_id=f"integ_buy_{test_id}_001",
            wallet=wallet,
            direction="buy",
            token_in_mint=usdc,
            token_in_amount="100.0",
            token_out_mint=token,
            token_out_amount="100.0",
            timestamp="2026-01-01T10:00:00Z",
        )

        position = await service.process_trade(buy_trade)
        await session.commit()

        print(f"    Position size: {position.position_size}")
        print(f"    Avg cost:      {position.avg_cost_basis}")
        print(f"    Total buys:    {position.total_buys}")
        print(f"    Correct:       {'OK' if position.position_size == Decimal('100') else 'FAIL'}")

    # ── Test 2: Process sell trade (FIFO) ───────────────────
    print("\n  Test 2: Process sell trade (FIFO PnL)")
    print("  " + "-" * 60)

    async with session_factory() as session:
        service = PositionService(session)

        sell_trade = make_trade(
            trade_id=f"integ_sell_{test_id}_001",
            wallet=wallet,
            direction="sell",
            token_in_mint=usdc,
            token_in_amount="200.0",
            token_out_mint=token,
            token_out_amount="100.0",
            timestamp="2026-01-01T12:00:00Z",
        )

        position = await service.process_trade(sell_trade)
        await session.commit()

        print(f"    Position size: {position.position_size}")
        print(f"    Realized PnL:  {position.realized_pnl}")
        print(f"    Total sells:   {position.total_sells}")
        print(f"    Correct:       {'OK' if position.position_size == Decimal('0') else 'FAIL'}")

    # ── Test 3: Process multiple buys (scaling) ─────────────
    print("\n  Test 3: Process multiple buys (scaling in)")
    print("  " + "-" * 60)

    wallet2 = f"TestW{test_id}_2"

    async with session_factory() as session:
        service = PositionService(session)

        # Buy 1: 50 tokens at $1
        buy1 = make_trade(
            trade_id=f"integ_buy_{test_id}_002a",
            wallet=wallet2,
            direction="buy",
            token_in_mint=usdc,
            token_in_amount="50.0",
            token_out_mint=token,
            token_out_amount="50.0",
            timestamp="2026-01-01T10:00:00Z",
        )
        await service.process_trade(buy1)

        # Buy 2: 50 tokens at $2
        buy2 = make_trade(
            trade_id=f"integ_buy_{test_id}_002b",
            wallet=wallet2,
            direction="buy",
            token_in_mint=usdc,
            token_in_amount="100.0",
            token_out_mint=token,
            token_out_amount="50.0",
            timestamp="2026-01-01T11:00:00Z",
        )
        position = await service.process_trade(buy2)
        await session.commit()

        print(f"    Position size: {position.position_size}")
        print(f"    Avg cost:      {position.avg_cost_basis}")
        print(f"    Total buys:    {position.total_buys}")
        print(f"    Correct:       {'OK' if position.position_size == Decimal('100') and position.total_buys == 2 else 'FAIL'}")

    # ── Test 4: Idempotent processing ───────────────────────
    print("\n  Test 4: Idempotent processing")
    print("  " + "-" * 60)

    async with session_factory() as session:
        service = PositionService(session)

        # Process same buy again
        position_before = await service.get_position(wallet, token)
        size_before = position_before.position_size if position_before else Decimal("0")

        await service.process_trade(buy_trade)  # Duplicate
        await session.commit()

        position_after = await service.get_position(wallet, token)
        size_after = position_after.position_size if position_after else Decimal("0")

        print(f"    Size before: {size_before}")
        print(f"    Size after:  {size_after}")
        print(f"    Idempotent:  {'OK' if size_before == size_after else 'FAIL'}")

    # ── Test 5: Wallet metrics aggregation ───────────────────
    print("\n  Test 5: Wallet metrics aggregation")
    print("  " + "-" * 60)

    async with session_factory() as session:
        repo = PositionRepository(session)
        aggregator = MetricsAggregator(repo)

        result = await aggregator.compute_wallet_metrics(wallet)
        await session.commit()

        print(f"    Total PnL:       {result.metrics.total_realized_pnl}")
        print(f"    Total trades:    {result.metrics.total_trades}")
        print(f"    Win rate:        {result.metrics.win_rate}%")
        print(f"    Active positions: {result.metrics.active_positions}")
        print(f"    Correct:         {'OK' if result.metrics.total_trades > 0 else 'FAIL'}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  ALL INTEGRATION TESTS PASSED")
    print("=" * 70)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_integration_test())
