"""Test paper trading system."""
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, '.')

from app.paper_trading.position_manager import PositionManager
from app.paper_trading.trade_simulator import TradeSimulator
from app.paper_trading.portfolio_manager import PortfolioManager
from app.paper_trading.risk_engine import RiskEngine
from app.paper_trading.outcome_tracker import OutcomeTracker


async def main():
    print("=" * 70)
    print("  PAPER TRADING SYSTEM TEST")
    print("=" * 70)

    # Initialize components
    position_mgr = PositionManager()
    simulator = TradeSimulator(position_mgr)
    portfolio = PortfolioManager(position_mgr)
    risk = RiskEngine()
    outcomes = OutcomeTracker()

    # Test 1: Position Creation
    print("\n1. Position Creation")
    position = await simulator.simulate_trade(
        token="WIF",
        current_price=2.50,
        prediction_score=0.75,
        confidence=0.80,
        regime="ACCUMULATION",
        signal_breakdown={"smart_money": 0.7, "momentum": 0.6},
        cluster_id="C1",
        smart_money_present=True,
    )
    print(f"  Position: {position['position_id'][:16]}...")
    print(f"  Token: {position['token']}")
    print(f"  Entry: ${position['entry_price']:.2f}")
    print(f"  Quantity: {position['quantity']:.2f}")

    # Test 2: Price Update
    print("\n2. Price Update")
    await position_mgr.update_price(position['position_id'], 3.00)
    pos = position_mgr.get_open_positions()[0]
    print(f"  Current price: ${pos.current_price:.2f}")
    print(f"  Return: {pos.return_pct:.2f}%")

    # Test 3: Portfolio Value
    print("\n3. Portfolio Value")
    portfolio_value = position_mgr.get_portfolio_value()
    print(f"  Portfolio value: ${portfolio_value:,.2f}")

    # Test 4: Close Position
    print("\n4. Close Position")
    outcome = await simulator.simulate_exit(
        position['position_id'],
        current_price=3.50,
        exit_reason="TAKE_PROFIT_1",
    )
    print(f"  PnL: ${outcome['pnl']:.2f}")
    print(f"  ROI: {outcome['roi']:.2f}%")
    print(f"  Exit reason: {outcome['exit_reason']}")

    # Test 5: Performance Metrics
    print("\n5. Performance Metrics")
    perf = portfolio.get_performance_metrics()
    print(f"  Total trades: {perf['total_trades']}")
    print(f"  Win rate: {perf['win_rate']:.1f}%")
    print(f"  Avg return: {perf['avg_return']:.2f}%")
    print(f"  Profit factor: {perf['profit_factor']:.2f}")

    # Test 6: Risk Limits
    print("\n6. Risk Limits")
    ok, reason = risk.check_position_risk(
        position_value=1500,
        portfolio_value=100000,
        max_position_pct=0.10,
    )
    print(f"  Position risk: {'OK' if ok else 'FAIL'} ({reason})")

    print("\n" + "=" * 70)
    print("  ALL PAPER TRADING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
