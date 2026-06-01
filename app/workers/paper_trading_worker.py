"""Paper trading worker — automatically manages virtual positions from predictions."""

from __future__ import annotations

import asyncio
import structlog
from datetime import datetime, timezone
from typing import Any

from app.paper_trading.position_manager import PositionManager
from app.paper_trading.trade_simulator import TradeSimulator
from app.paper_trading.portfolio_manager import PortfolioManager
from app.paper_trading.outcome_tracker import OutcomeTracker

logger = structlog.get_logger(__name__)


class PaperTradingWorker:
    """Continuously manages virtual positions from live predictions."""

    def __init__(self) -> None:
        self._position_mgr = PositionManager()
        self._simulator = TradeSimulator(self._position_mgr)
        self._portfolio = PortfolioManager(self._position_mgr)
        self._outcomes = OutcomeTracker()
        self._running = False
        self._price_cache: dict[str, float] = {}

    async def run(self) -> None:
        """Main loop: update prices, check exits, take snapshots."""
        self._running = True
        logger.info("paper_worker.starting")

        while self._running:
            try:
                await self._update_cycle()
            except Exception as e:
                logger.error("paper_worker.error", error=str(e))
            await asyncio.sleep(60)  # 1 minute interval

        logger.info("paper_worker.stopped")

    async def shutdown(self) -> None:
        """Signal shutdown."""
        self._running = False

    async def _update_cycle(self) -> None:
        """Run one update cycle."""
        # 1. Update prices for all open positions
        await self._update_prices()

        # 2. Check exit conditions
        exits = await self._simulator.check_exits()
        for exit in exits:
            self._outcomes.record_outcome(
                position_id=exit["position_id"],
                token=exit["token"],
                entry_price=exit["entry_price"],
                exit_price=exit["exit_price"],
                quantity=exit["quantity"],
                holding_hours=exit["holding_period_hours"],
                exit_reason=exit["exit_reason"],
                signal_attribution=exit.get("signal_attribution", {}),
            )

        # 3. Take portfolio snapshot
        snapshot = await self._portfolio.take_snapshot()

        logger.info(
            "paper_worker.cycle_complete",
            open_positions=snapshot.open_positions,
            portfolio_value=snapshot.total_value,
            win_rate=snapshot.win_rate,
        )

    async def _update_prices(self) -> None:
        """Update prices for all open positions."""
        for position in self._position_mgr.get_open_positions():
            # Get current price from cache or API
            current_price = self._price_cache.get(position.token, position.entry_price)
            await self._position_mgr.update_price(position.position_id, current_price)

    async def process_prediction(
        self,
        token: str,
        current_price: float,
        prediction_score: float,
        confidence: float,
        regime: str,
        signal_breakdown: dict[str, float],
        cluster_id: str,
        smart_money_present: bool,
    ) -> dict[str, Any] | None:
        """Process a live prediction and create position if warranted."""
        return await self._simulator.simulate_trade(
            token=token,
            current_price=current_price,
            prediction_score=prediction_score,
            confidence=confidence,
            regime=regime,
            signal_breakdown=signal_breakdown,
            cluster_id=cluster_id,
            smart_money_present=smart_money_present,
        )

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get current portfolio summary."""
        pm = self._position_mgr
        return {
            "portfolio_value": pm.get_portfolio_value(),
            "cash": pm._cash,
            "open_positions": len(pm.get_open_positions()),
            "closed_positions": len(pm.get_closed_positions()),
        }
