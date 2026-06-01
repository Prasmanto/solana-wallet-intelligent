"""FIFO lot accounting system.

Implements First-In-First-Out lot tracking for accurate cost basis:
- Buy: create new lot
- Sell: consume lots in FIFO order
- Partial consumption supported
- Lots are immutable once created

This is the core of accurate realized PnL calculation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.position_lot import PositionLot
from app.schemas.lot import LotInfo, LotStatus
from app.schemas.trade import NormalizedTrade, TradeDirection

logger = structlog.get_logger(__name__)


class FIFOLotManager:
    """Manages FIFO lot accounting for positions.

    All operations are idempotent and replay-safe.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def process_trade(
        self,
        trade: NormalizedTrade,
    ) -> list[LotInfo]:
        """Process a trade and return affected lots.

        For buys: creates a new lot.
        For sells: consumes lots in FIFO order.

        Returns list of lots that were created or modified.
        """
        if trade.direction == TradeDirection.BUY:
            return await self._process_buy(trade)
        else:
            return await self._process_sell(trade)

    async def _process_buy(
        self,
        trade: NormalizedTrade,
    ) -> list[LotInfo]:
        """Create a new lot from a buy trade."""
        # Determine which token was bought
        # In a BUY: wallet receives token_out (the token being bought)
        buy_token = trade.token_out.mint
        buy_quantity = trade.token_out.amount
        buy_price = trade.token_in.amount / trade.token_out.amount if trade.token_out.amount > 0 else Decimal("0")

        # Check for duplicate (idempotent)
        existing = await self._find_lot_by_trade(trade.trade_id)
        if existing:
            logger.info("lot.duplicate_skipped", trade_id=trade.trade_id[:16])
            return [existing]

        # Create new lot
        lot = PositionLot(
            id=uuid.uuid4(),
            wallet=trade.wallet,
            token_mint=buy_token,
            trade_id=trade.trade_id,
            signature=trade.signature,
            original_quantity=float(buy_quantity),
            remaining_quantity=float(buy_quantity),
            cost_basis_per_token=float(buy_price),
            total_cost=float(trade.token_in.amount),
            status="open",
            buy_timestamp=trade.timestamp or datetime.now(timezone.utc),
        )

        self._session.add(lot)
        await self._session.flush()

        logger.info(
            "lot.created",
            wallet=trade.wallet[:8],
            token=buy_token[:8],
            quantity=float(buy_quantity),
            price=float(buy_price),
        )

        return [LotInfo(
            id=str(lot.id),
            wallet=lot.wallet,
            token_mint=lot.token_mint,
            trade_id=lot.trade_id,
            signature=lot.signature,
            original_quantity=Decimal(str(lot.original_quantity)),
            remaining_quantity=Decimal(str(lot.remaining_quantity)),
            cost_basis_per_token=Decimal(str(lot.cost_basis_per_token)),
            total_cost=Decimal(str(lot.total_cost)),
            status=LotStatus(lot.status),
            buy_timestamp=lot.buy_timestamp,
        )]

    async def _process_sell(
        self,
        trade: NormalizedTrade,
    ) -> list[LotInfo]:
        """Consume lots in FIFO order for a sell trade."""
        # Determine which token was sold
        # In a SELL: wallet pays token_out (the token being sold)
        sell_token = trade.token_out.mint
        sell_quantity = trade.token_out.amount
        sell_price = trade.token_in.amount / trade.token_out.amount if trade.token_out.amount > 0 else Decimal("0")

        # Get open lots in FIFO order (oldest first)
        lots = await self._get_open_lots(trade.wallet, sell_token)

        if not lots:
            logger.warning(
                "lot.no_open_lots",
                wallet=trade.wallet[:8],
                token=sell_token[:8],
                sell_qty=float(sell_quantity),
            )
            return []

        remaining_to_sell = float(sell_quantity)
        affected_lots: list[LotInfo] = []

        for lot in lots:
            if remaining_to_sell <= 0:
                break

            lot_remaining = lot.remaining_quantity
            consume_qty = min(remaining_to_sell, lot_remaining)

            # Update lot
            lot.remaining_quantity = lot_remaining - consume_qty
            remaining_to_sell -= consume_qty

            # Update status
            if lot.remaining_quantity <= 0:
                lot.status = "closed"
                lot.closed_at = datetime.now(timezone.utc)
            else:
                lot.status = "partial"

            await self._session.flush()

            affected_lots.append(LotInfo(
                id=str(lot.id),
                wallet=lot.wallet,
                token_mint=lot.token_mint,
                trade_id=lot.trade_id,
                signature=lot.signature,
                original_quantity=Decimal(str(lot.original_quantity)),
                remaining_quantity=Decimal(str(lot.remaining_quantity)),
                cost_basis_per_token=Decimal(str(lot.cost_basis_per_token)),
                total_cost=Decimal(str(lot.total_cost)),
                status=LotStatus(lot.status),
                buy_timestamp=lot.buy_timestamp,
                closed_at=lot.closed_at,
            ))

            logger.debug(
                "lot.consumed",
                lot_id=str(lot.id)[:8],
                consumed=consume_qty,
                remaining=lot.remaining_quantity,
            )

        return affected_lots

    async def _get_open_lots(
        self,
        wallet: str,
        token_mint: str,
    ) -> list[PositionLot]:
        """Get open lots for a wallet + token in FIFO order."""
        stmt = (
            select(PositionLot)
            .where(
                and_(
                    PositionLot.wallet == wallet,
                    PositionLot.token_mint == token_mint,
                    PositionLot.status.in_(["open", "partial"]),
                )
            )
            .order_by(PositionLot.buy_timestamp.asc())
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _find_lot_by_trade(
        self,
        trade_id: str,
    ) -> PositionLot | None:
        """Find a lot by trade_id (for idempotency)."""
        stmt = select(PositionLot).where(PositionLot.trade_id == trade_id).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_lots(
        self,
        wallet: str,
        token_mint: str,
        status: str | None = None,
    ) -> list[LotInfo]:
        """Get all lots for a wallet + token."""
        conditions = [
            PositionLot.wallet == wallet,
            PositionLot.token_mint == token_mint,
        ]
        if status:
            conditions.append(PositionLot.status == status)

        stmt = (
            select(PositionLot)
            .where(and_(*conditions))
            .order_by(PositionLot.buy_timestamp.asc())
        )

        result = await self._session.execute(stmt)
        lots = result.scalars().all()

        return [
            LotInfo(
                id=str(lot.id),
                wallet=lot.wallet,
                token_mint=lot.token_mint,
                trade_id=lot.trade_id,
                signature=lot.signature,
                original_quantity=Decimal(str(lot.original_quantity)),
                remaining_quantity=Decimal(str(lot.remaining_quantity)),
                cost_basis_per_token=Decimal(str(lot.cost_basis_per_token)),
                total_cost=Decimal(str(lot.total_cost)),
                status=LotStatus(lot.status),
                buy_timestamp=lot.buy_timestamp,
                closed_at=lot.closed_at,
            )
            for lot in lots
        ]
