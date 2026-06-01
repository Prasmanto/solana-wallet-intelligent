"""Position repository — async CRUD for wallet positions and lots.

Design:
- Idempotent inserts
- Optimized for wallet + token queries
- FIFO lot queries
- Aggregation-friendly queries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.position_lot import PositionLot
from app.infrastructure.database.models.wallet_metrics import WalletMetrics
from app.infrastructure.database.models.wallet_position import WalletPosition
from app.schemas.lot import LotInfo, LotStatus
from app.schemas.metrics import TokenMetrics, WalletMetrics as WalletMetricsSchema
from app.schemas.position import PositionState

logger = structlog.get_logger(__name__)


class PositionRepository:
    """Async repository for position and lot persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Position Operations ─────────────────────────────────

    async def upsert_position(
        self,
        *,
        wallet: str,
        token_mint: str,
        position_size: float,
        avg_cost_basis: float,
        total_cost_basis: float,
        realized_pnl: float,
        realized_roi: float,
        total_buys: int,
        total_sells: int,
        total_buy_volume: float,
        total_sell_volume: float,
        total_fees_paid: float,
        first_buy_at: datetime | None = None,
        last_buy_at: datetime | None = None,
        first_sell_at: datetime | None = None,
        last_sell_at: datetime | None = None,
        last_trade_at: datetime | None = None,
        hold_duration_seconds: int = 0,
        last_trade_id: str = "",
        event_version: int = 1,
    ) -> WalletPosition:
        """Insert or update a wallet position."""
        now = datetime.now(timezone.utc)

        stmt = (
            pg_insert(WalletPosition)
            .values(
                id=uuid.uuid4(),
                wallet=wallet,
                token_mint=token_mint,
                position_size=position_size,
                avg_cost_basis=avg_cost_basis,
                total_cost_basis=total_cost_basis,
                realized_pnl=realized_pnl,
                realized_roi=realized_roi,
                total_buys=total_buys,
                total_sells=total_sells,
                total_buy_volume=total_buy_volume,
                total_sell_volume=total_sell_volume,
                total_fees_paid=total_fees_paid,
                first_buy_at=first_buy_at,
                last_buy_at=last_buy_at,
                first_sell_at=first_sell_at,
                last_sell_at=last_sell_at,
                last_trade_at=last_trade_at,
                hold_duration_seconds=hold_duration_seconds,
                last_trade_id=last_trade_id,
                event_version=event_version,
                last_processed_at=now,
            )
            .on_conflict_do_update(
                index_elements=["wallet", "token_mint"],
                set_={
                    "position_size": position_size,
                    "avg_cost_basis": avg_cost_basis,
                    "total_cost_basis": total_cost_basis,
                    "realized_pnl": realized_pnl,
                    "realized_roi": realized_roi,
                    "total_buys": total_buys,
                    "total_sells": total_sells,
                    "total_buy_volume": total_buy_volume,
                    "total_sell_volume": total_sell_volume,
                    "total_fees_paid": total_fees_paid,
                    "first_buy_at": first_buy_at,
                    "last_buy_at": last_buy_at,
                    "first_sell_at": first_sell_at,
                    "last_sell_at": last_sell_at,
                    "last_trade_at": last_trade_at,
                    "hold_duration_seconds": hold_duration_seconds,
                    "last_trade_id": last_trade_id,
                    "event_version": event_version,
                    "last_processed_at": now,
                },
            )
            .returning(WalletPosition)
        )

        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_position(
        self,
        wallet: str,
        token_mint: str,
    ) -> WalletPosition | None:
        """Get a position by wallet + token."""
        stmt = select(WalletPosition).where(
            and_(
                WalletPosition.wallet == wallet,
                WalletPosition.token_mint == token_mint,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_wallet_positions(
        self,
        wallet: str,
        include_zero: bool = False,
    ) -> list[WalletPosition]:
        """Get all positions for a wallet."""
        conditions = [WalletPosition.wallet == wallet]
        if not include_zero:
            conditions.append(WalletPosition.position_size > 0)

        stmt = (
            select(WalletPosition)
            .where(and_(*conditions))
            .order_by(WalletPosition.last_trade_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_positions_by_token(
        self,
        token_mint: str,
    ) -> list[WalletPosition]:
        """Get all positions for a token (across wallets)."""
        stmt = (
            select(WalletPosition)
            .where(
                and_(
                    WalletPosition.token_mint == token_mint,
                    WalletPosition.position_size > 0,
                )
            )
            .order_by(WalletPosition.position_size.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Lot Operations ──────────────────────────────────────

    async def insert_lot(
        self,
        *,
        wallet: str,
        token_mint: str,
        trade_id: str,
        signature: str,
        original_quantity: float,
        remaining_quantity: float,
        cost_basis_per_token: float,
        total_cost: float,
        status: str = "open",
        buy_timestamp: datetime,
    ) -> PositionLot:
        """Insert a new lot."""
        lot = PositionLot(
            id=uuid.uuid4(),
            wallet=wallet,
            token_mint=token_mint,
            trade_id=trade_id,
            signature=signature,
            original_quantity=original_quantity,
            remaining_quantity=remaining_quantity,
            cost_basis_per_token=cost_basis_per_token,
            total_cost=total_cost,
            status=status,
            buy_timestamp=buy_timestamp,
        )
        self._session.add(lot)
        await self._session.flush()
        return lot

    async def get_open_lots(
        self,
        wallet: str,
        token_mint: str,
    ) -> list[PositionLot]:
        """Get open lots in FIFO order."""
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

    async def update_lot(
        self,
        lot_id: uuid.UUID,
        *,
        remaining_quantity: float,
        status: str,
        closed_at: datetime | None = None,
    ) -> None:
        """Update a lot's remaining quantity and status."""
        stmt = (
            update(PositionLot)
            .where(PositionLot.id == lot_id)
            .values(
                remaining_quantity=remaining_quantity,
                status=status,
                closed_at=closed_at,
            )
        )
        await self._session.execute(stmt)

    async def get_lots_by_trade(
        self,
        trade_id: str,
    ) -> list[PositionLot]:
        """Get lots created by a specific trade."""
        stmt = select(PositionLot).where(PositionLot.trade_id == trade_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Metrics Operations ──────────────────────────────────

    async def upsert_metrics(
        self,
        *,
        wallet: str,
        total_realized_pnl: float,
        total_realized_roi: float,
        total_fees_paid: float,
        net_pnl: float,
        total_wins: int,
        total_losses: int,
        win_rate: float,
        avg_win_pnl: float,
        avg_loss_pnl: float,
        best_trade_pnl: float,
        worst_trade_pnl: float,
        best_trade_token: str,
        worst_trade_token: str,
        total_unique_tokens: int,
        active_positions: int,
        total_trades: int,
        total_buys: int,
        total_sells: int,
        total_buy_volume: float,
        total_sell_volume: float,
        total_volume: float,
        avg_hold_duration_seconds: int,
        avg_position_size: float,
        max_position_size: float,
        first_trade_at: datetime | None = None,
        last_trade_at: datetime | None = None,
        metrics_version: int = 1,
        last_trade_id: str = "",
    ) -> WalletMetrics:
        """Insert or update wallet metrics."""
        now = datetime.now(timezone.utc)

        stmt = (
            pg_insert(WalletMetrics)
            .values(
                id=uuid.uuid4(),
                wallet=wallet,
                total_realized_pnl=total_realized_pnl,
                total_realized_roi=total_realized_roi,
                total_fees_paid=total_fees_paid,
                net_pnl=net_pnl,
                total_wins=total_wins,
                total_losses=total_losses,
                win_rate=win_rate,
                avg_win_pnl=avg_win_pnl,
                avg_loss_pnl=avg_loss_pnl,
                best_trade_pnl=best_trade_pnl,
                worst_trade_pnl=worst_trade_pnl,
                best_trade_token=best_trade_token,
                worst_trade_token=worst_trade_token,
                total_unique_tokens=total_unique_tokens,
                active_positions=active_positions,
                total_trades=total_trades,
                total_buys=total_buys,
                total_sells=total_sells,
                total_buy_volume=total_buy_volume,
                total_sell_volume=total_sell_volume,
                total_volume=total_volume,
                avg_hold_duration_seconds=avg_hold_duration_seconds,
                avg_position_size=avg_position_size,
                max_position_size=max_position_size,
                first_trade_at=first_trade_at,
                last_trade_at=last_trade_at,
                last_updated_at=now,
                metrics_version=metrics_version,
                last_trade_id=last_trade_id,
            )
            .on_conflict_do_update(
                index_elements=["wallet"],
                set_={
                    "total_realized_pnl": total_realized_pnl,
                    "total_realized_roi": total_realized_roi,
                    "total_fees_paid": total_fees_paid,
                    "net_pnl": net_pnl,
                    "total_wins": total_wins,
                    "total_losses": total_losses,
                    "win_rate": win_rate,
                    "avg_win_pnl": avg_win_pnl,
                    "avg_loss_pnl": avg_loss_pnl,
                    "best_trade_pnl": best_trade_pnl,
                    "worst_trade_pnl": worst_trade_pnl,
                    "best_trade_token": best_trade_token,
                    "worst_trade_token": worst_trade_token,
                    "total_unique_tokens": total_unique_tokens,
                    "active_positions": active_positions,
                    "total_trades": total_trades,
                    "total_buys": total_buys,
                    "total_sells": total_sells,
                    "total_buy_volume": total_buy_volume,
                    "total_sell_volume": total_sell_volume,
                    "total_volume": total_volume,
                    "avg_hold_duration_seconds": avg_hold_duration_seconds,
                    "avg_position_size": avg_position_size,
                    "max_position_size": max_position_size,
                    "first_trade_at": first_trade_at,
                    "last_trade_at": last_trade_at,
                    "last_updated_at": now,
                    "metrics_version": metrics_version,
                    "last_trade_id": last_trade_id,
                },
            )
            .returning(WalletMetrics)
        )

        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_wallet_metrics(
        self,
        wallet: str,
    ) -> WalletMetrics | None:
        """Get wallet metrics."""
        stmt = select(WalletMetrics).where(WalletMetrics.wallet == wallet)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_top_wallets(
        self,
        metric: str = "total_realized_pnl",
        limit: int = 10,
    ) -> list[WalletMetrics]:
        """Get top wallets by a metric."""
        column = getattr(WalletMetrics, metric, WalletMetrics.total_realized_pnl)
        stmt = (
            select(WalletMetrics)
            .order_by(column.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Aggregation Queries ─────────────────────────────────

    async def get_wallet_token_metrics(
        self,
        wallet: str,
    ) -> list[TokenMetrics]:
        """Get per-token metrics for a wallet from positions."""
        stmt = (
            select(WalletPosition)
            .where(WalletPosition.wallet == wallet)
            .order_by(WalletPosition.last_trade_at.desc())
        )
        result = await self._session.execute(stmt)
        positions = result.scalars().all()

        return [
            TokenMetrics(
                wallet=p.wallet,
                token_mint=p.token_mint,
                position_size=Decimal(str(p.position_size)),
                avg_cost_basis=Decimal(str(p.avg_cost_basis)),
                total_cost_basis=Decimal(str(p.total_cost_basis)),
                realized_pnl=Decimal(str(p.realized_pnl)),
                realized_roi=Decimal(str(p.realized_roi)),
                total_buys=p.total_buys,
                total_sells=p.total_sells,
                total_buy_volume=Decimal(str(p.total_buy_volume)),
                total_sell_volume=Decimal(str(p.total_sell_volume)),
                first_buy_at=p.first_buy_at,
                last_trade_at=p.last_trade_at,
                hold_duration_seconds=p.hold_duration_seconds,
                total_fees_paid=Decimal(str(p.total_fees_paid)),
            )
            for p in positions
        ]
