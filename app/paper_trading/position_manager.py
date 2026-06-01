"""Position manager — manages virtual positions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.paper_trading.position_models import PaperPosition

logger = structlog.get_logger(__name__)

# Risk limits
INITIAL_CAPITAL = 100_000.0
RISK_PER_TRADE = 0.01
MAX_OPEN_POSITIONS = 20
MAX_SECTOR_EXPOSURE = 0.10


class PositionManager:
    """Manages virtual positions for paper trading."""

    def __init__(self) -> None:
        self._positions: dict[str, PaperPosition] = {}
        self._closed_positions: list[dict[str, Any]] = []
        self._cash = INITIAL_CAPITAL
        self._initial_capital = INITIAL_CAPITAL

    async def create_position(
        self,
        token: str,
        entry_price: float,
        prediction_score: float,
        confidence: float,
        regime: str,
        signal_breakdown: dict[str, float],
        cluster_id: str,
        smart_money_present: bool,
    ) -> PaperPosition | None:
        """Create a virtual position if risk limits allow."""
        # Check risk limits
        if not self._check_risk_limits(token, entry_price):
            logger.warning("position.risk_limit_exceeded", token=token)
            return None

        # Calculate position size (1% of portfolio)
        position_size = (self._cash * RISK_PER_TRADE) / entry_price

        position = PaperPosition(
            position_id=str(uuid.uuid4()),
            token=token,
            entry_price=entry_price,
            quantity=position_size,
            prediction_score=prediction_score,
            confidence=confidence,
            regime=regime,
            signal_breakdown=signal_breakdown,
            cluster_id=cluster_id,
            smart_money_present=smart_money_present,
            entry_time=datetime.now(timezone.utc).isoformat(),
        )

        self._positions[position.position_id] = position
        self._cash -= position_size * entry_price

        logger.info(
            "position.created",
            position_id=position.position_id[:16],
            token=token,
            quantity=position_size,
            entry_price=entry_price,
        )

        return position

    async def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
    ) -> dict[str, Any] | None:
        """Close a virtual position."""
        if position_id not in self._positions:
            return None

        position = self._positions[position_id]

        # Calculate PnL
        pnl = (exit_price - position.entry_price) * position.quantity
        roi = ((exit_price - position.entry_price) / position.entry_price) * 100

        # Create outcome
        outcome = {
            "position_id": position_id,
            "token": position.token,
            "entry_time": position.entry_time,
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "holding_period_hours": self._calc_holding_hours(position.entry_time),
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "quantity": position.quantity,
            "pnl": float(pnl),
            "roi": float(roi),
            "max_roi": position.max_return,
            "max_drawdown": position.max_drawdown,
            "win_loss": "WIN" if pnl > 0 else "LOSS",
            "exit_reason": exit_reason,
            "signal_attribution": position.signal_breakdown,
        }

        # Update cash
        self._cash += position.quantity * exit_price

        # Move to closed
        del self._positions[position_id]
        self._closed_positions.append(outcome)

        logger.info(
            "position.closed",
            position_id=position_id[:16],
            token=position.token,
            pnl=float(pnl),
            roi=float(roi),
            exit_reason=exit_reason,
        )

        return outcome

    async def update_price(
        self,
        position_id: str,
        current_price: float,
    ) -> None:
        """Update current price for a position."""
        if position_id not in self._positions:
            return

        position = self._positions[position_id]
        position.current_price = current_price

        # Calculate return
        position.return_pct = ((current_price - position.entry_price) / position.entry_price) * 100

        # Track max return and drawdown
        if position.return_pct > position.max_return:
            position.max_return = position.return_pct
        if position.return_pct < position.max_drawdown:
            position.max_drawdown = position.return_pct

    def _check_risk_limits(self, token: str, price: float) -> bool:
        """Check if position creation is allowed."""
        # Max open positions
        if len(self._positions) >= MAX_OPEN_POSITIONS:
            return False

        # Max sector exposure (simplified: 10% per token)
        token_exposure = sum(
            p.quantity * p.entry_price
            for p in self._positions.values()
            if p.token == token
        )
        if token_exposure > self._initial_capital * MAX_SECTOR_EXPOSURE:
            return False

        return True

    def _calc_holding_hours(self, entry_time: str) -> float:
        """Calculate holding period in hours."""
        try:
            entry = datetime.fromisoformat(entry_time)
            delta = datetime.now(timezone.utc) - entry
            return delta.total_seconds() / 3600
        except:
            return 0.0

    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value."""
        cash = self._cash
        positions_value = sum(
            p.quantity * p.current_price
            for p in self._positions.values()
        )
        return cash + positions_value

    def get_open_positions(self) -> list[PaperPosition]:
        """Get all open positions."""
        return list(self._positions.values())

    def get_closed_positions(self) -> list[dict[str, Any]]:
        """Get all closed positions."""
        return self._closed_positions
