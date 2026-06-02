"""Paper trading status endpoint.

Provides:
- GET /status — Paper trading portfolio status, candidates, and price feed health
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter
from sqlalchemy import func, select

from app.config.settings import settings
from app.infrastructure.database.models.paper_trading import (
    PaperPortfolioSnapshot,
    PaperPosition,
    PaperTradeOutcome,
)
from app.infrastructure.database.session import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post(
    "/close-position",
    summary="Admin: close a paper position by token mint",
)
async def close_position(
    token_mint: str,
    exit_reason: str = "STALE_ACTIVITY",
    outcome_status: str = "INVALID_CANDIDATE",
) -> dict[str, Any]:
    """Close an OPEN paper position for a specific token.

    Administrative endpoint for closing stale or invalid positions.
    Does NOT execute real trades.
    """
    from app.workers.paper_trading_worker import PaperTradingWorker

    worker = PaperTradingWorker(session_factory=async_session_factory)
    closed = await worker.close_position_by_token(
        token_mint=token_mint,
        exit_reason=exit_reason,
        outcome_status=outcome_status,
    )

    if closed:
        return {"status": "closed", "token_mint": token_mint, "exit_reason": exit_reason, "outcome_status": outcome_status}
    else:
        return {"status": "not_found", "token_mint": token_mint}


@router.get(
    "/status",
    summary="Paper trading status",
)
async def paper_status() -> dict[str, Any]:
    """Return paper trading portfolio status.

    Includes:
    - enabled/dry_run flags
    - position counts by status
    - latest candidates and skip reasons
    - portfolio value and realized PnL
    - last snapshot time
    - price feed health check
    """
    async with async_session_factory() as session:
        # Count by status
        open_count = await _count_by_status(session, "OPEN")
        closed_count = await _count_by_status(session, "CLOSED")
        skipped_count = await _count_by_status(session, "SKIPPED")

        # Realized PnL
        pnl_stmt = select(
            func.coalesce(func.sum(PaperTradeOutcome.pnl_usd), 0.0)
        )
        pnl_result = await session.execute(pnl_stmt)
        realized_pnl = float(pnl_result.scalar() or 0.0)

        # Latest SKIPPED candidates (last 10)
        latest_stmt = (
            select(PaperPosition)
            .where(PaperPosition.status == "SKIPPED")
            .order_by(PaperPosition.created_at.desc())
            .limit(10)
        )
        latest_result = await session.execute(latest_stmt)
        latest_skipped = latest_result.scalars().all()

        candidates = []
        skip_reasons: dict[str, int] = {}
        for pos in latest_skipped:
            meta = pos.metadata_json or {}
            reason = meta.get("skip_reason", "unknown")
            activity = meta.get("token_activity", {})
            candidates.append({
                "token": pos.token_mint,
                "score": pos.entry_score,
                "rank": meta.get("rank", 0),
                "regime": meta.get("regime", ""),
                "stage": meta.get("stage", ""),
                "skip_reason": reason,
                "token_events_15m": activity.get("events_15m", 0),
                "unique_wallets_15m": activity.get("unique_wallets_15m", 0),
                "last_token_activity_age_minutes": activity.get("last_activity_age_minutes", -1),
                "activity_filter_passed": activity.get("passed", None),
                "created_at": pos.created_at.isoformat() if pos.created_at else "",
            })
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        # Latest OPEN positions (for visibility)
        open_stmt = (
            select(PaperPosition)
            .where(PaperPosition.status == "OPEN")
            .order_by(PaperPosition.created_at.desc())
            .limit(20)
        )
        open_result = await session.execute(open_stmt)
        open_positions = open_result.scalars().all()

        open_list = []
        for pos in open_positions:
            meta = pos.metadata_json or {}
            open_list.append({
                "id": str(pos.id),
                "token": pos.token_mint,
                "entry_score": pos.entry_score,
                "entry_price": pos.entry_price,
                "current_price": meta.get("current_price"),
                "current_roi": meta.get("current_roi"),
                "max_return": meta.get("max_return"),
                "max_drawdown": meta.get("max_drawdown"),
                "virtual_size_usd": pos.virtual_size_usd,
                "rank": meta.get("rank", 0),
                "regime": meta.get("regime", ""),
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else "",
            })

        # Last snapshot
        snapshot_stmt = (
            select(PaperPortfolioSnapshot)
            .order_by(PaperPortfolioSnapshot.created_at.desc())
            .limit(1)
        )
        snapshot_result = await session.execute(snapshot_stmt)
        last_snapshot = snapshot_result.scalar_one_or_none()

        virtual_capital = settings.PAPER_VIRTUAL_CAPITAL

        # Price feed health check
        price_feed = await _check_price_feed()

        return {
            "enabled": settings.PAPER_TRADING_ENABLED,
            "dry_run": settings.PAPER_TRADING_DRY_RUN,
            "open_positions": open_count,
            "closed_positions": closed_count,
            "skipped_positions": skipped_count,
            "open_position_list": open_list,
            "latest_candidates": candidates,
            "latest_skip_reasons": skip_reasons,
            "portfolio_value": round(virtual_capital + realized_pnl, 2),
            "realized_pnl": round(realized_pnl, 4),
            "virtual_capital": virtual_capital,
            "last_snapshot_time": (
                last_snapshot.created_at.isoformat()
                if last_snapshot and last_snapshot.created_at
                else None
            ),
            "price_feed": price_feed,
        }


async def _check_price_feed() -> dict[str, Any]:
    """Quick Jupiter V3 price feed health check."""
    try:
        import httpx

        url = settings.JUPITER_PRICE_BASE_URL
        # Test with SOL mint
        sol_mint = "So11111111111111111111111111111111111111112"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"ids": sol_mint})
            resp.raise_for_status()
            data = resp.json()

            if sol_mint in data and isinstance(data[sol_mint], dict):
                sol_price = data[sol_mint].get("usdPrice")
                return {
                    "endpoint": url,
                    "status": "ok",
                    "sol_price_usd": round(sol_price, 2) if sol_price else None,
                }
            else:
                return {
                    "endpoint": url,
                    "status": "unexpected_response",
                    "sol_price_usd": None,
                }
    except Exception as e:
        return {
            "endpoint": settings.JUPITER_PRICE_BASE_URL,
            "status": "error",
            "error": str(e)[:200],
            "sol_price_usd": None,
        }


async def _count_by_status(session: Any, status: str) -> int:
    """Count paper positions by status."""
    stmt = select(func.count()).select_from(PaperPosition).where(
        PaperPosition.status == status
    )
    result = await session.execute(stmt)
    return result.scalar() or 0
