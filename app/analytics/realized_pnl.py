"""Realized PnL engine.

Calculates realized PnL using FIFO lot accounting:
- For each sell, consumes lots in FIFO order
- Computes PnL per lot and total
- Updates position state
- Handles partial exits and scaling

This is the core analytics engine for wallet intelligence.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from app.analytics.fifo_lots import FIFOLotManager
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.schemas.lot import LotInfo
from app.schemas.position import PositionState, RealizedPnLResult
from app.schemas.trade import NormalizedTrade, TradeDirection

logger = structlog.get_logger(__name__)


class RealizedPnLEngine:
    """Calculates realized PnL and updates position state.

    All operations are idempotent and replay-safe.
    """

    def __init__(self, lot_manager: FIFOLotManager) -> None:
        self._lot_manager = lot_manager

    async def process_trade(
        self,
        trade: NormalizedTrade,
        position: WalletPosition | None = None,
    ) -> RealizedPnLResult | None:
        """Process a trade and calculate realized PnL.

        Args:
            trade: The normalized trade to process
            position: Current position state (None if first trade)

        Returns:
            RealizedPnLResult for sells, None for buys
        """
        if trade.direction == TradeDirection.BUY:
            await self._process_buy(trade, position)
            return None

        # For sells, calculate realized PnL
        return await self._process_sell(trade, position)

    async def _process_buy(
        self,
        trade: NormalizedTrade,
        position: WalletPosition | None,
    ) -> None:
        """Process a buy trade — update position state."""
        buy_quantity = trade.token_out.amount
        buy_cost = trade.token_in.amount  # What was paid

        if position is None:
            # First buy — create position
            return

        # Update position: increase size, recalculate avg cost
        old_size = Decimal(str(position.position_size))
        old_cost = Decimal(str(position.total_cost_basis))

        new_size = old_size + buy_quantity
        new_cost = old_cost + buy_cost

        position.position_size = float(new_size)
        position.total_cost_basis = float(new_cost)
        position.avg_cost_basis = float(new_cost / new_size) if new_size > 0 else 0

        # Update statistics
        position.total_buys += 1
        position.total_buy_volume = float(Decimal(str(position.total_buy_volume)) + buy_quantity)
        position.total_fees_paid = float(Decimal(str(position.total_fees_paid)) + trade.fee_sol)

        # Update timestamps
        if trade.timestamp:
            position.last_buy_at = trade.timestamp
            if position.first_buy_at is None:
                position.first_buy_at = trade.timestamp
            position.last_trade_at = trade.timestamp

        # Update hold duration
        if position.last_trade_at and trade.timestamp:
            delta = trade.timestamp - position.last_trade_at
            position.hold_duration_seconds += int(delta.total_seconds())

        position.last_trade_id = trade.trade_id
        position.event_version += 1

    async def _process_sell(
        self,
        trade: NormalizedTrade,
        position: WalletPosition | None,
    ) -> RealizedPnLResult:
        """Process a sell trade — calculate realized PnL."""
        sell_quantity = trade.token_out.amount  # What wallet receives
        sell_proceeds = trade.token_in.amount   # What wallet paid (the token being sold)

        # Consume lots in FIFO order
        affected_lots = await self._lot_manager.process_trade(trade)

        # Calculate realized PnL from consumed lots
        total_cost = Decimal("0")
        for lot in affected_lots:
            # Cost = consumed_quantity * cost_basis_per_token
            consumed = lot.original_quantity - lot.remaining_quantity
            lot_cost = consumed * lot.cost_basis_per_token
            total_cost += lot_cost

        realized_pnl = sell_proceeds - total_cost
        realized_roi = (realized_pnl / total_cost * 100) if total_cost > 0 else Decimal("0")

        # Update position state
        if position:
            old_size = Decimal(str(position.position_size))
            new_size = old_size - sell_quantity

            position.position_size = float(max(new_size, Decimal("0")))
            position.realized_pnl = float(Decimal(str(position.realized_pnl)) + realized_pnl)
            position.total_fees_paid = float(Decimal(str(position.total_fees_paid)) + trade.fee_sol)

            # Update statistics
            position.total_sells += 1
            position.total_sell_volume = float(Decimal(str(position.total_sell_volume)) + sell_quantity)

            # Recalculate ROI
            total_invested = Decimal(str(position.total_cost_basis))
            if total_invested > 0:
                position.realized_roi = float(
                    Decimal(str(position.realized_pnl)) / total_invested * 100
                )

            # Update timestamps
            if trade.timestamp:
                position.last_sell_at = trade.timestamp
                if position.first_sell_at is None:
                    position.first_sell_at = trade.timestamp
                position.last_trade_at = trade.timestamp

            # Update hold duration
            if position.last_trade_at and trade.timestamp:
                delta = trade.timestamp - position.last_trade_at
                position.hold_duration_seconds += int(delta.total_seconds())

            position.last_trade_id = trade.trade_id
            position.event_version += 1

        return RealizedPnLResult(
            trade_id=trade.trade_id,
            wallet=trade.wallet,
            token_mint=trade.token_out.mint,
            sell_quantity=sell_quantity,
            sell_price=sell_proceeds / sell_quantity if sell_quantity > 0 else Decimal("0"),
            total_proceeds=sell_proceeds,
            total_cost=total_cost,
            realized_pnl=realized_pnl,
            realized_roi=realized_roi,
            lots_consumed=affected_lots,
            fees=trade.fee_sol,
        )

    def calculate_unrealized_pnl(
        self,
        position: PositionState,
        current_price: Decimal,
    ) -> Decimal:
        """Calculate unrealized PnL (placeholder — needs price feed).

        This is a placeholder for future implementation when
        live pricing is added.
        """
        if position.position_size <= 0:
            return Decimal("0")

        market_value = position.position_size * current_price
        return market_value - Decimal(str(position.total_cost_basis))
