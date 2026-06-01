"""Risk engine — validates and enforces risk limits."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class RiskEngine:
    """Enforces risk limits for paper trading."""

    def check_position_risk(
        self,
        position_value: float,
        portfolio_value: float,
        max_position_pct: float = 0.10,
    ) -> tuple[bool, str]:
        """Check if position exceeds risk limits."""
        if portfolio_value <= 0:
            return False, "portfolio_empty"

        position_pct = position_value / portfolio_value
        if position_pct > max_position_pct:
            return False, f"position_exceeds_{max_position_pct*100:.0f}_pct"

        return True, "ok"

    def check_drawdown(
        self,
        current_value: float,
        peak_value: float,
        max_drawdown_pct: float = 0.20,
    ) -> bool:
        """Check if drawdown exceeds limit."""
        if peak_value <= 0:
            return False

        drawdown = (peak_value - current_value) / peak_value
        return drawdown > max_drawdown_pct

    def calculate_position_size(
        self,
        portfolio_value: float,
        risk_per_trade: float = 0.01,
        entry_price: float = 1.0,
    ) -> float:
        """Calculate position size based on risk."""
        if entry_price <= 0:
            return 0.0
        risk_amount = portfolio_value * risk_per_trade
        return risk_amount / entry_price
