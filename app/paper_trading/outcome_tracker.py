"""Outcome tracker — tracks and stores trade outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OutcomeTracker:
    """Tracks outcomes for closed trades."""

    def __init__(self) -> None:
        self._outcomes: list[dict[str, Any]] = []

    def record_outcome(
        self,
        position_id: str,
        token: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        holding_hours: float,
        exit_reason: str,
        signal_attribution: dict[str, float],
    ) -> dict[str, Any]:
        """Record a trade outcome."""
        pnl = (exit_price - entry_price) * quantity
        roi = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0

        outcome = {
            "position_id": position_id,
            "token": token,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": float(pnl),
            "roi": float(roi),
            "holding_hours": holding_hours,
            "exit_reason": exit_reason,
            "win_loss": "WIN" if pnl > 0 else "LOSS",
            "signal_attribution": signal_attribution,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

        self._outcomes.append(outcome)

        logger.info(
            "outcome.recorded",
            position_id=position_id[:16],
            token=token,
            pnl=float(pnl),
            roi=float(roi),
            exit_reason=exit_reason,
        )

        return outcome

    def get_outcomes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent outcomes."""
        return self._outcomes[-limit:]

    def get_performance_summary(self) -> dict[str, Any]:
        """Compute performance summary."""
        if not self._outcomes:
            return {"total_trades": 0}

        total = len(self._outcomes)
        wins = sum(1 for o in self._outcomes if o.get("win_loss") == "WIN")
        losses = total - wins

        returns = [o.get("roi", 0) for o in self._outcomes]
        avg_return = sum(returns) / len(returns) if returns else 0

        total_pnl = sum(o.get("pnl", 0) for o in self._outcomes)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100) if total > 0 else 0.0,
            "avg_return": avg_return,
            "total_pnl": total_pnl,
            "profit_factor": self._calc_profit_factor(returns),
        }

    def _calc_profit_factor(self, returns: list[float]) -> float:
        """Calculate profit factor."""
        if not returns:
            return 0.0
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")
