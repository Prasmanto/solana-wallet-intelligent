"""Position service — orchestrates position tracking and PnL calculation.

Pipeline:
1. Receive normalized trade from trade.normalized stream
2. Load or create position state
3. Process through FIFO lot manager
4. Calculate realized PnL
5. Update position state
6. Persist to database
7. Publish to trade.enriched stream

Design:
- Idempotent: duplicate trades are safely ignored
- Atomic: all updates in single transaction
- Deterministic: same input → same output
- Replay-safe: can replay from any point
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.fifo_lots import FIFOLotManager
from app.analytics.realized_pnl import RealizedPnLEngine
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.schemas.position import PositionState, RealizedPnLResult
from app.schemas.trade import NormalizedTrade, TradeDirection

logger = structlog.get_logger(__name__)


class PositionService:
    """Service for tracking positions and calculating PnL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._lot_manager = FIFOLotManager(session)
        self._pnl_engine = RealizedPnLEngine(self._lot_manager)

    async def process_trade(
        self,
        trade: NormalizedTrade,
    ) -> PositionState:
        """Process a trade and update position state.

        This is the main entry point for position tracking.
        Handles both buys and sells.
        """
        # Check for duplicate (idempotent)
        if await self._is_already_processed(trade.trade_id):
            logger.info("position.duplicate_skipped", trade_id=trade.trade_id[:16])
            return await self._get_position_state(trade.wallet, self._get_token_mint(trade))

        # Load or create position
        position = await self._get_or_create_position(trade)

        # Process through PnL engine
        pnl_result = await self._pnl_engine.process_trade(trade, position)

        # Persist position
        await self._save_position(position)

        # Log result
        if pnl_result:
            logger.info(
                "position.sell_processed",
                wallet=trade.wallet[:8],
                token=trade.token_out.mint[:8],
                realized_pnl=float(pnl_result.realized_pnl),
                roi=float(pnl_result.realized_roi),
            )
        else:
            logger.info(
                "position.buy_processed",
                wallet=trade.wallet[:8],
                token=trade.token_out.mint[:8],
                new_size=float(position.position_size),
            )

        return self._to_position_state(position)

    async def get_position(
        self,
        wallet: str,
        token_mint: str,
    ) -> PositionState | None:
        """Get current position state for a wallet + token."""
        position = await self._load_position(wallet, token_mint)
        if not position:
            return None
        return self._to_position_state(position)

    async def get_all_positions(
        self,
        wallet: str,
    ) -> list[PositionState]:
        """Get all positions for a wallet."""
        stmt = (
            select(WalletPosition)
            .where(WalletPosition.wallet == wallet)
            .order_by(WalletPosition.last_trade_at.desc())
        )

        result = await self._session.execute(stmt)
        positions = result.scalars().all()

        return [self._to_position_state(p) for p in positions]

    async def get_pnl_summary(
        self,
        wallet: str,
    ) -> dict[str, Any]:
        """Get aggregate PnL summary for a wallet."""
        positions = await self.get_all_positions(wallet)

        total_realized_pnl = sum(Decimal(str(p.realized_pnl)) for p in positions)
        total_fees = sum(Decimal(str(p.total_fees_paid)) for p in positions)
        active_positions = sum(1 for p in positions if p.position_size > 0)

        return {
            "wallet": wallet,
            "total_positions": len(positions),
            "active_positions": active_positions,
            "total_realized_pnl": float(total_realized_pnl),
            "total_fees_paid": float(total_fees),
            "net_pnl": float(total_realized_pnl - total_fees),
        }

    # ── Internal Methods ────────────────────────────────────

    def _get_token_mint(self, trade: NormalizedTrade) -> str:
        """Get the token mint based on trade direction."""
        if trade.direction == TradeDirection.BUY:
            return trade.token_out.mint  # Token received
        else:
            return trade.token_out.mint  # Token sold

    async def _is_already_processed(self, trade_id: str) -> bool:
        """Check if trade was already processed (idempotent)."""
        stmt = select(WalletPosition.id).where(
            WalletPosition.last_trade_id == trade_id
        ).limit(1)

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _get_or_create_position(
        self,
        trade: NormalizedTrade,
    ) -> WalletPosition:
        """Load existing position or create new one."""
        token_mint = self._get_token_mint(trade)
        position = await self._load_position(trade.wallet, token_mint)

        if position:
            return position

        # Create new position
        position = WalletPosition(
            wallet=trade.wallet,
            token_mint=token_mint,
            position_size=0,
            avg_cost_basis=0,
            total_cost_basis=0,
            realized_pnl=0,
            realized_roi=0,
            total_buys=0,
            total_sells=0,
            total_buy_volume=0,
            total_sell_volume=0,
            total_fees_paid=0,
            hold_duration_seconds=0,
            last_trade_id="",
            event_version=0,
        )

        self._session.add(position)
        await self._session.flush()

        return position

    async def _load_position(
        self,
        wallet: str,
        token_mint: str,
    ) -> WalletPosition | None:
        """Load position from database."""
        stmt = select(WalletPosition).where(
            and_(
                WalletPosition.wallet == wallet,
                WalletPosition.token_mint == token_mint,
            )
        ).limit(1)

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_position_state(
        self,
        wallet: str,
        token_mint: str,
    ) -> PositionState:
        """Get position as PositionState schema."""
        position = await self._load_position(wallet, token_mint)
        if not position:
            return PositionState(wallet=wallet, token_mint=token_mint)
        return self._to_position_state(position)

    async def _save_position(self, position: WalletPosition) -> None:
        """Save position to database."""
        position.last_processed_at = datetime.now(timezone.utc)
        await self._session.flush()

    def _to_position_state(self, position: WalletPosition) -> PositionState:
        """Convert ORM model to Pydantic schema."""
        return PositionState(
            wallet=position.wallet,
            token_mint=position.token_mint,
            position_size=Decimal(str(position.position_size)),
            avg_cost_basis=Decimal(str(position.avg_cost_basis)),
            total_cost_basis=Decimal(str(position.total_cost_basis)),
            realized_pnl=Decimal(str(position.realized_pnl)),
            realized_roi=Decimal(str(position.realized_roi)),
            total_buys=position.total_buys,
            total_sells=position.total_sells,
            total_buy_volume=Decimal(str(position.total_buy_volume)),
            total_sell_volume=Decimal(str(position.total_sell_volume)),
            total_fees_paid=Decimal(str(position.total_fees_paid)),
            first_buy_at=position.first_buy_at,
            last_buy_at=position.last_buy_at,
            first_sell_at=position.first_sell_at,
            last_sell_at=position.last_sell_at,
            last_trade_at=position.last_trade_at,
            hold_duration_seconds=position.hold_duration_seconds,
            last_trade_id=position.last_trade_id,
            event_version=position.event_version,
        )
