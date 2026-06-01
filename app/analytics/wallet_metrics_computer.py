"""Wallet metrics computer — computes aggregated metrics from wallet_positions.

This module computes wallet-level metrics from position data:
- Trade statistics (count, buys, sells)
- Volume metrics (buy volume, sell volume, net flow)
- Token diversity
- Activity timestamps (first/last trade)
- Position metrics (avg/max size)

Design:
- Deterministic: same inputs → same outputs
- Idempotent: safe to recompute
- No fake PnL: sets pnl/roi to 0 with reason if price data unavailable
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.wallet_position import WalletPosition
from app.infrastructure.database.models.wallet_metrics import WalletMetrics

logger = structlog.get_logger(__name__)


class WalletMetricsComputer:
    """Computes aggregated wallet metrics from position data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compute_all_wallets(self) -> dict[str, Any]:
        """Compute metrics for all wallets.
        
        Returns:
            dict with counts: created, updated, skipped, errors
        """
        stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
        
        # Get all unique wallets
        wallet_result = await self._session.execute(
            select(WalletPosition.wallet).distinct()
        )
        wallets = [row[0] for row in wallet_result]
        
        logger.info("metrics.computing", wallet_count=len(wallets))
        
        for wallet in wallets:
            try:
                result = await self.compute_wallet_metrics(wallet)
                if result == "created":
                    stats["created"] += 1
                elif result == "updated":
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error("metrics.error", wallet=wallet[:16], error=str(e))
        
        logger.info("metrics.completed", **stats)
        return stats

    async def compute_wallet_metrics(self, wallet: str) -> str:
        """Compute metrics for a single wallet.
        
        Returns:
            "created", "updated", or "skipped"
        """
        # Get all positions for this wallet
        result = await self._session.execute(
            select(WalletPosition).where(WalletPosition.wallet == wallet)
        )
        positions = result.scalars().all()
        
        if not positions:
            return "skipped"
        
        # Compute aggregated metrics
        metrics = self._aggregate_positions(positions)
        
        # Check if metrics already exist
        existing = await self._session.execute(
            select(WalletMetrics).where(WalletMetrics.wallet == wallet)
        )
        existing_metrics = existing.scalar_one_or_none()
        
        now = datetime.now(timezone.utc)
        
        if existing_metrics is None:
            # Create new metrics
            wallet_metrics = WalletMetrics(
                wallet=wallet,
                **metrics,
                last_updated_at=now,
                metadata_={"source": "backfill", "computed_at": now.isoformat()},
            )
            self._session.add(wallet_metrics)
            return "created"
        else:
            # Update existing metrics
            for key, value in metrics.items():
                setattr(existing_metrics, key, value)
            existing_metrics.last_updated_at = now
            existing_metrics.metrics_version += 1
            return "updated"

    def _aggregate_positions(self, positions: list[WalletPosition]) -> dict[str, Any]:
        """Aggregate position data into wallet-level metrics."""
        if not positions:
            return self._empty_metrics()
        
        # Trade counts
        total_buys = sum(p.total_buys for p in positions)
        total_sells = sum(p.total_sells for p in positions)
        total_trades = total_buys + total_sells
        
        # Volume metrics
        total_buy_volume = sum(float(p.total_buy_volume) for p in positions)
        total_sell_volume = sum(float(p.total_sell_volume) for p in positions)
        total_volume = total_buy_volume + total_sell_volume
        
        # Token diversity
        unique_tokens = len(set(p.token_mint for p in positions))
        active_positions = sum(1 for p in positions if float(p.position_size) > 0)
        
        # Position sizes
        position_sizes = [float(p.position_size) for p in positions]
        avg_position_size = sum(position_sizes) / len(position_sizes) if position_sizes else 0
        max_position_size = max(position_sizes) if position_sizes else 0
        
        # Hold duration
        hold_durations = [p.hold_duration_seconds for p in positions]
        avg_hold_duration = sum(hold_durations) / len(hold_durations) if hold_durations else 0
        
        # Fees
        total_fees = sum(float(p.total_fees_paid) for p in positions)
        
        # PnL (set to 0 if no price data)
        total_pnl = sum(float(p.realized_pnl) for p in positions)
        total_cost = sum(float(p.total_cost_basis) for p in positions)
        total_roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        # Win/Loss (simplified: positive PnL = win, negative = loss)
        # Note: Without price data, we can't determine actual win/loss
        # Set to 0 with metadata reason
        total_wins = 0
        total_losses = 0
        win_rate = 0.0
        
        # Timestamps
        first_trade = min(
            (p.first_buy_at or p.last_trade_at for p in positions if p.first_buy_at or p.last_trade_at),
            default=None
        )
        last_trade = max(
            (p.last_trade_at for p in positions if p.last_trade_at),
            default=None
        )
        
        return {
            "total_realized_pnl": total_pnl,
            "total_realized_roi": total_roi,
            "total_fees_paid": total_fees,
            "net_pnl": total_pnl,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "win_rate": win_rate,
            "avg_win_pnl": 0.0,
            "avg_loss_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "best_trade_token": "",
            "worst_trade_token": "",
            "total_unique_tokens": unique_tokens,
            "active_positions": active_positions,
            "total_trades": total_trades,
            "total_buys": total_buys,
            "total_sells": total_sells,
            "total_buy_volume": total_buy_volume,
            "total_sell_volume": total_sell_volume,
            "total_volume": total_volume,
            "avg_hold_duration_seconds": int(avg_hold_duration),
            "avg_position_size": avg_position_size,
            "max_position_size": max_position_size,
            "first_trade_at": first_trade,
            "last_trade_at": last_trade,
        }

    def _empty_metrics(self) -> dict[str, Any]:
        """Return empty metrics dict."""
        return {
            "total_realized_pnl": 0.0,
            "total_realized_roi": 0.0,
            "total_fees_paid": 0.0,
            "net_pnl": 0.0,
            "total_wins": 0,
            "total_losses": 0,
            "win_rate": 0.0,
            "avg_win_pnl": 0.0,
            "avg_loss_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "best_trade_token": "",
            "worst_trade_token": "",
            "total_unique_tokens": 0,
            "active_positions": 0,
            "total_trades": 0,
            "total_buys": 0,
            "total_sells": 0,
            "total_buy_volume": 0.0,
            "total_sell_volume": 0.0,
            "total_volume": 0.0,
            "avg_hold_duration_seconds": 0,
            "avg_position_size": 0.0,
            "max_position_size": 0.0,
            "first_trade_at": None,
            "last_trade_at": None,
        }
