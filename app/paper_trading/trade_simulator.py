"""Trade simulator — simulates virtual trades from predictions."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.paper_trading.position_manager import PositionManager

logger = structlog.get_logger(__name__)


class TradeSimulator:
    """Simulates virtual trades from prediction signals."""

    def __init__(self, position_manager: PositionManager) -> None:
        self._position_manager = position_manager

    async def simulate_trade(
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
        """Simulate a virtual trade from a prediction signal."""
        # Only trade if score exceeds threshold
        if prediction_score < 0.65:
            return None

        # Create position
        position = await self._position_manager.create_position(
            token=token,
            entry_price=current_price,
            prediction_score=prediction_score,
            confidence=confidence,
            regime=regime,
            signal_breakdown=signal_breakdown,
            cluster_id=cluster_id,
            smart_money_present=smart_money_present,
        )

        if not position:
            return None

        return {
            "position_id": position.position_id,
            "token": token,
            "entry_price": current_price,
            "quantity": position.quantity,
            "prediction_score": prediction_score,
            "timestamp": position.entry_time,
        }

    async def simulate_exit(
        self,
        position_id: str,
        current_price: float,
        exit_reason: str,
    ) -> dict[str, Any] | None:
        """Simulate a virtual exit."""
        return await self._position_manager.close_position(
            position_id=position_id,
            exit_price=current_price,
            exit_reason=exit_reason,
        )

    async def check_exits(self) -> list[dict[str, Any]]:
        """Check all open positions for exit conditions."""
        exits = []

        for position in self._position_manager.get_open_positions():
            if not position.current_price:
                continue

            exit_reason = self._check_exit_conditions(position)
            if exit_reason:
                outcome = await self._position_manager.close_position(
                    position.position_id,
                    position.current_price,
                    exit_reason,
                )
                if outcome:
                    exits.append(outcome)

        return exits

    def _check_exit_conditions(self, position) -> str | None:
        """Check if position should be closed."""
        if position.return_pct >= 20:
            return "TAKE_PROFIT_1"
        elif position.return_pct >= 50:
            return "TAKE_PROFIT_2"
        elif position.return_pct <= -10:
            return "STOP_LOSS"

        # Time-based exit (24 hours)
        try:
            entry = datetime.fromisoformat(position.entry_time)
            hours = (datetime.now(timezone.utc) - entry).total_seconds() / 3600
            if hours >= 24:
                return "TIME_BASED_EXIT"
        except:
            pass

        return None
