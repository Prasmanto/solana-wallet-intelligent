"""Portfolio manager — tracks overall portfolio state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.paper_trading.position_manager import PositionManager
from app.paper_trading.position_models import PortfolioSnapshot

logger = structlog.get_logger(__name__)


class PortfolioManager:
    """Manages portfolio state and snapshots."""

    def __init__(self, position_manager: PositionManager) -> None:
        self._position_manager = position_manager
        self._snapshots: list[PortfolioSnapshot] = []

    async def take_snapshot(self) -> PortfolioSnapshot:
        """Take a snapshot of current portfolio state."""
        pm = self._position_manager

        open_positions = pm.get_open_positions()
        closed_positions = pm.get_closed_positions()

        # Calculate daily PnL
        daily_pnl = sum(
            p.get("roi", 0) * p.get("quantity", 0) * p.get("exit_price", 0) / 100
            for p in closed_positions
            if p.get("exit_time", "").startswith(datetime.now().strftime("%Y-%m-%d"))
        )

        # Calculate win rate
        wins = sum(1 for p in closed_positions if p.get("win_loss") == "WIN")
        total_closed = len(closed_positions)
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_value=pm.get_portfolio_value(),
            cash=pm._cash,
            open_positions=len(open_positions),
            closed_positions=total_closed,
            total_pnl=pm.get_portfolio_value() - pm._initial_capital,
            daily_pnl=daily_pnl,
            win_rate=win_rate,
        )

        self._snapshots.append(snapshot)

        logger.info(
            "portfolio.snapshot",
            total_value=snapshot.total_value,
            open_positions=snapshot.open_positions,
            win_rate=snapshot.win_rate,
        )

        return snapshot

    def get_snapshots(self, limit: int = 10) -> list[PortfolioSnapshot]:
        """Get recent portfolio snapshots."""
        return self._snapshots[-limit:]

    def get_performance_metrics(self) -> dict[str, Any]:
        """Compute portfolio performance metrics."""
        closed = self._position_manager.get_closed_positions()
        if not closed:
            return {"total_trades": 0}

        returns = [p.get("roi", 0) for p in closed]
        wins = sum(1 for p in closed if p.get("win_loss") == "WIN")
        total = len(closed)

        return {
            "total_trades": total,
            "win_rate": (wins / total * 100) if total > 0 else 0.0,
            "avg_return": sum(returns) / len(returns) if returns else 0.0,
            "max_return": max(returns) if returns else 0.0,
            "max_drawdown": min(returns) if returns else 0.0,
            "profit_factor": self._calc_profit_factor(returns),
            "sharpe_ratio": self._calc_sharpe(returns),
        }

    def _calc_profit_factor(self, returns: list[float]) -> float:
        """Calculate profit factor."""
        if not returns:
            return 0.0
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    def _calc_sharpe(self, returns: list[float], risk_free: float = 0.0) -> float:
        """Calculate Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        avg_return = sum(returns) / len(returns)
        std_dev = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
        if std_dev == 0:
            return 0.0
        return (avg_return - risk_free) / std_dev
