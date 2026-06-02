"""Wallet metrics aggregation service.

Computes wallet-level metrics from position data:
- Total realized PnL
- Win/loss rate
- Best/worst trades
- Average hold duration
- Position size statistics

Design:
- Deterministic: same inputs → same outputs
- Replay-safe: versioned metrics
- Idempotent: safe to recompute
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from app.infrastructure.database.models.wallet_position import WalletPosition
from app.infrastructure.database.repositories.position_repo import PositionRepository
from app.schemas.metrics import AggregationResult, TokenMetrics, WalletMetrics

logger = structlog.get_logger(__name__)


class MetricsAggregator:
    """Aggregates position data into wallet-level metrics."""

    def __init__(self, repo: PositionRepository) -> None:
        self._repo = repo

    async def compute_wallet_metrics(
        self,
        wallet: str,
    ) -> AggregationResult:
        """Compute aggregated metrics for a wallet.

        This is the main aggregation entry point.
        Reads all positions and computes wallet-level metrics.
        """
        import time

        start_time = time.time()

        # Get all positions for the wallet
        positions = await self._repo.get_wallet_positions(wallet, include_zero=True)

        # Get per-token metrics
        token_metrics = await self._repo.get_wallet_token_metrics(wallet)

        # Compute aggregated metrics
        metrics = self._aggregate_positions(wallet, positions)

        # Clamp Numeric(20,9) overflow — max absolute value is 10^11 - 1
        _MAX_NUMERIC = 99_999_999_999.999999999
        _MIN_NUMERIC = -99_999_999_999.999999999
        _MAX_SMALL = 999_999.9999
        _MIN_SMALL = -999_999.9999

        import math

        def _safe_float(v, small: bool = False) -> float:
            """Convert Decimal/int/float to safe float, clamped to Numeric range.

            small=True clamps to Numeric(10,4) range (for roi, win_rate).
            """
            lo = _MIN_SMALL if small else _MIN_NUMERIC
            hi = _MAX_SMALL if small else _MAX_NUMERIC
            try:
                f = float(v)
            except (TypeError, ValueError, OverflowError):
                return 0.0
            if math.isnan(f) or math.isinf(f):
                logger.warning(
                    "metrics.clamped_extreme",
                    wallet=wallet[:8],
                    value=str(v)[:50],
                )
                return 0.0
            if f > hi or f < lo:
                logger.warning(
                    "metrics.clamped_overflow",
                    wallet=wallet[:8],
                    original=f,
                )
                return max(lo, min(hi, f))
            return f

        # Persist metrics
        await self._repo.upsert_metrics(
            wallet=wallet,
            total_realized_pnl=_safe_float(metrics.total_realized_pnl),
            total_realized_roi=_safe_float(metrics.total_realized_roi, small=True),
            total_fees_paid=_safe_float(metrics.total_fees_paid),
            net_pnl=_safe_float(metrics.net_pnl),
            total_wins=metrics.total_wins,
            total_losses=metrics.total_losses,
            win_rate=_safe_float(metrics.win_rate, small=True),
            avg_win_pnl=_safe_float(metrics.avg_win_pnl),
            avg_loss_pnl=_safe_float(metrics.avg_loss_pnl),
            best_trade_pnl=_safe_float(metrics.best_trade_pnl),
            worst_trade_pnl=_safe_float(metrics.worst_trade_pnl),
            best_trade_token=metrics.best_trade_token,
            worst_trade_token=metrics.worst_trade_token,
            total_unique_tokens=metrics.total_unique_tokens,
            active_positions=metrics.active_positions,
            total_trades=metrics.total_trades,
            total_buys=metrics.total_buys,
            total_sells=metrics.total_sells,
            total_buy_volume=_safe_float(metrics.total_buy_volume),
            total_sell_volume=_safe_float(metrics.total_sell_volume),
            total_volume=_safe_float(metrics.total_volume),
            avg_hold_duration_seconds=metrics.avg_hold_duration_seconds,
            avg_position_size=_safe_float(metrics.avg_position_size),
            max_position_size=_safe_float(metrics.max_position_size),
            first_trade_at=metrics.first_trade_at,
            last_trade_at=metrics.last_trade_at,
            metrics_version=metrics.metrics_version,
            last_trade_id=metrics.last_trade_id or "",
        )

        aggregation_time = (time.time() - start_time) * 1000

        result = AggregationResult(
            wallet=wallet,
            metrics=metrics,
            token_metrics=token_metrics,
            trades_processed=len(positions),
            aggregation_time_ms=aggregation_time,
            computed_at=datetime.now(timezone.utc),
        )

        logger.info(
            "metrics.aggregated",
            wallet=wallet[:8],
            positions=len(positions),
            total_pnl=float(metrics.total_realized_pnl),
            win_rate=float(metrics.win_rate),
            time_ms=aggregation_time,
        )

        return result

    def _aggregate_positions(
        self,
        wallet: str,
        positions: list[WalletPosition],
    ) -> WalletMetrics:
        """Compute aggregated metrics from positions.

        All Decimal sums are clamped to safe ranges before arithmetic
        to prevent Numeric(20,9) overflow from extreme raw token amounts.
        """
        if not positions:
            return WalletMetrics(wallet=wallet)

        # Safe Decimal cap: Numeric(20,9) max is 10^11 - 1
        _DEC_CAP = Decimal("99999999999")
        _DEC_NEG_CAP = Decimal("-99999999999")

        def _safe_decimal(v, cap: Decimal = _DEC_CAP) -> Decimal:
            """Convert to Decimal safely, clamped to prevent overflow."""
            try:
                d = Decimal(str(v))
            except (TypeError, ValueError, InvalidOperation):
                return Decimal("0")
            if d.is_nan() or d.is_infinite():
                return Decimal("0")
            return max(-cap, min(cap, d))

        def _safe_sum(items: list[Decimal], cap: Decimal = _DEC_CAP) -> Decimal:
            """Sum Decimal items with per-item clamping and final clamp."""
            total = Decimal("0")
            for item in items:
                clamped = max(-cap, min(cap, item))
                total += clamped
                # Clamp running total to prevent overflow
                total = max(-cap, min(cap, total))
            return total

        from decimal import InvalidOperation

        # Collect all realized PnLs for win/loss calculation — clamp each value
        pnls = [_safe_decimal(p.realized_pnl) for p in positions]
        winning_pnls = [p for p in pnls if p > 0]
        losing_pnls = [p for p in pnls if p < 0]

        # Basic sums — safe_sum prevents overflow
        total_realized_pnl = _safe_sum(pnls)
        total_fees = _safe_sum([_safe_decimal(p.total_fees_paid) for p in positions])
        total_buys = sum(p.total_buys for p in positions)
        total_sells = sum(p.total_sells for p in positions)
        total_buy_volume = _safe_sum([_safe_decimal(p.total_buy_volume) for p in positions])
        total_sell_volume = _safe_sum([_safe_decimal(p.total_sell_volume) for p in positions])

        # Win/loss metrics
        total_wins = len(winning_pnls)
        total_losses = len(losing_pnls)
        total_closed = total_wins + total_losses
        win_rate = _safe_decimal(total_wins / total_closed * 100, cap=Decimal("100")) if total_closed > 0 else Decimal("0")

        avg_win = sum(winning_pnls) / len(winning_pnls) if winning_pnls else Decimal("0")
        avg_loss = sum(losing_pnls) / len(losing_pnls) if losing_pnls else Decimal("0")

        # Clamp avg_win/avg_loss to prevent division artifacts
        avg_win = max(-_DEC_CAP, min(_DEC_CAP, avg_win))
        avg_loss = max(-_DEC_CAP, min(_DEC_CAP, avg_loss))

        # Best/worst trades
        best_pnl = max(pnls) if pnls else Decimal("0")
        worst_pnl = min(pnls) if pnls else Decimal("0")

        best_token = ""
        worst_token = ""
        for p in positions:
            p_pnl = _safe_decimal(p.realized_pnl)
            if p_pnl == best_pnl:
                best_token = p.token_mint
            if p_pnl == worst_pnl:
                worst_token = p.token_mint

        # Position metrics
        active_positions = sum(1 for p in positions if p.position_size > 0)
        position_sizes = [_safe_decimal(p.position_size) for p in positions if p.position_size > 0]
        avg_position = sum(position_sizes) / len(position_sizes) if position_sizes else Decimal("0")
        max_position = max(position_sizes) if position_sizes else Decimal("0")

        # Clamp position sizes
        avg_position = max(-_DEC_CAP, min(_DEC_CAP, avg_position))
        max_position = max(-_DEC_CAP, min(_DEC_CAP, max_position))

        # Hold duration
        total_hold = sum(p.hold_duration_seconds for p in positions)
        avg_hold = total_hold // len(positions) if positions else 0

        # Timestamps
        first_trade = min(
            (p.first_buy_at for p in positions if p.first_buy_at),
            default=None,
        )
        last_trade = max(
            (p.last_trade_at for p in positions if p.last_trade_at),
            default=None,
        )

        # Version
        max_version = max((p.event_version for p in positions), default=0)

        return WalletMetrics(
            wallet=wallet,
            total_realized_pnl=total_realized_pnl,
            total_realized_roi=Decimal("0"),  # Computed from PnL / cost basis
            total_fees_paid=total_fees,
            net_pnl=total_realized_pnl - total_fees,
            total_wins=total_wins,
            total_losses=total_losses,
            win_rate=win_rate,
            avg_win_pnl=avg_win,
            avg_loss_pnl=avg_loss,
            best_trade_pnl=best_pnl,
            worst_trade_pnl=worst_pnl,
            best_trade_token=best_token,
            worst_trade_token=worst_token,
            total_unique_tokens=len(positions),
            active_positions=active_positions,
            total_trades=total_buys + total_sells,
            total_buys=total_buys,
            total_sells=total_sells,
            total_buy_volume=total_buy_volume,
            total_sell_volume=total_sell_volume,
            total_volume=total_buy_volume + total_sell_volume,
            avg_hold_duration_seconds=avg_hold,
            avg_position_size=avg_position,
            max_position_size=max_position,
            first_trade_at=first_trade,
            last_trade_at=last_trade,
            metrics_version=max_version + 1,
            computed_at=datetime.now(timezone.utc),
        )
