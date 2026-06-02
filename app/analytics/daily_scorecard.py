"""Daily Alpha Scorecard — 24h analytics report.

Queries existing tables to produce a comprehensive daily report covering:
- Pipeline activity
- Signal quality
- Candidate filtering
- Paper trading performance
- Outcome quality
- System health

Design:
- Read-only queries against existing tables
- No mutation of any data
- Graceful handling of empty/missing tables
- Returns dict for JSON or renders markdown
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.infrastructure.database.models.paper_trading import (
    PaperPortfolioSnapshot,
    PaperPosition,
    PaperTradeOutcome,
)
from app.infrastructure.database.models.prediction import Prediction
from app.infrastructure.database.models.raw_event import RawEvent
from app.infrastructure.database.models.token_ranking import TokenRanking
from app.infrastructure.database.models.wallet_feature import WalletFeature
from app.infrastructure.database.models.wallet_metrics import WalletMetrics
from app.infrastructure.database.models.wallet_position import WalletPosition

logger = structlog.get_logger(__name__)


async def generate_scorecard(
    session: AsyncSession,
    hours: int = 24,
) -> dict[str, Any]:
    """Generate the daily alpha scorecard.

    Args:
        session: async DB session
        hours: lookback window in hours (default 24)

    Returns:
        dict with all scorecard sections
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)

    sections = {}

    # 1. Pipeline activity
    sections["pipeline_activity"] = await _pipeline_activity(session, window_start)

    # 2. Signal activity
    sections["signal_activity"] = await _signal_activity(session, window_start)

    # 3. Candidate filtering
    sections["candidate_filtering"] = await _candidate_filtering(session, window_start)

    # 4. Paper trading performance
    sections["paper_trading"] = await _paper_trading_performance(session, window_start)

    # 5. Outcome quality
    sections["outcome_quality"] = await _outcome_quality(session, window_start)

    # 6. System health
    sections["system_health"] = await _system_health(session)

    # Verdict
    sections["verdict"] = _compute_verdict(sections)
    sections["recommended_action"] = _recommended_action(sections)

    # Metadata
    sections["meta"] = {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "window_start": window_start.isoformat(),
    }

    return sections


# ── Section builders ────────────────────────────────────────


async def _pipeline_activity(session: AsyncSession, since: datetime) -> dict[str, Any]:
    """Section 1: Pipeline activity counts."""
    try:
        raw_count = await _count_since(session, RawEvent, RawEvent.created_at, since)

        # wallet_positions — use last_trade_at (no created_at on this model)
        pos_stmt = select(func.count()).select_from(WalletPosition).where(
            WalletPosition.last_trade_at >= since
        )
        pos_count = (await session.execute(pos_stmt)).scalar() or 0

        # wallet_metrics — use last_updated_at
        metrics_stmt = select(func.count()).select_from(WalletMetrics).where(
            WalletMetrics.last_updated_at >= since
        )
        metrics_count = (await session.execute(metrics_stmt)).scalar() or 0

        # wallet_features — use computed_at
        feat_stmt = select(func.count()).select_from(WalletFeature).where(
            WalletFeature.computed_at >= since
        )
        feat_count = (await session.execute(feat_stmt)).scalar() or 0

        pred_count = await _count_since(session, Prediction, Prediction.created_at, since)
        rank_count = await _count_since(session, TokenRanking, TokenRanking.created_at, since)

        return {
            "raw_events": raw_count,
            "wallet_positions": pos_count,
            "wallet_metrics": metrics_count,
            "wallet_features": feat_count,
            "predictions": pred_count,
            "rankings": rank_count,
        }
    except Exception as e:
        logger.error("scorecard.pipeline_activity.error", error=str(e)[:200])
        return {"raw_events": 0, "wallet_positions": 0, "wallet_metrics": 0,
                "wallet_features": 0, "predictions": 0, "rankings": 0, "error": str(e)[:100]}


async def _signal_activity(session: AsyncSession, since: datetime) -> dict[str, Any]:
    """Section 2: Prediction signal quality."""
    try:
        # Basic counts
        pred_count = (await session.execute(
            select(func.count()).select_from(Prediction).where(Prediction.created_at >= since)
        )).scalar() or 0

        avg_score = float((await session.execute(
            select(func.coalesce(func.avg(Prediction.predicted_score), 0.0))
            .where(Prediction.created_at >= since)
        )).scalar() or 0.0)

        # Score distribution buckets
        buckets = {}
        for label, lo, hi in [("0.0-0.2", 0.0, 0.2), ("0.2-0.4", 0.2, 0.4),
                               ("0.4-0.6", 0.4, 0.6), ("0.6-0.8", 0.6, 0.8),
                               ("0.8-1.0", 0.8, 1.001)]:
            cnt = (await session.execute(
                select(func.count()).select_from(Prediction).where(
                    Prediction.created_at >= since,
                    Prediction.predicted_score >= lo,
                    Prediction.predicted_score < hi,
                )
            )).scalar() or 0
            buckets[label] = cnt

        # Regime distribution (from metadata_json)
        regime_stmt = text("""
            SELECT metadata_json->>'regime' as regime, COUNT(*) as cnt
            FROM predictions
            WHERE created_at >= :since AND metadata_json->>'regime' IS NOT NULL
            GROUP BY regime ORDER BY cnt DESC LIMIT 10
        """)
        regime_rows = (await session.execute(regime_stmt, {"since": since})).fetchall()
        regimes = {row[0]: row[1] for row in regime_rows}

        # Stage distribution
        stage_stmt = text("""
            SELECT metadata_json->>'stage' as stage, COUNT(*) as cnt
            FROM predictions
            WHERE created_at >= :since AND metadata_json->>'stage' IS NOT NULL
            GROUP BY stage ORDER BY cnt DESC LIMIT 10
        """)
        stage_rows = (await session.execute(stage_stmt, {"since": since})).fetchall()
        stages = {row[0]: row[1] for row in stage_rows}

        # Top 20 tokens by score
        top_score_stmt = text("""
            SELECT token, MAX(predicted_score) as max_score, COUNT(*) as pred_count
            FROM predictions WHERE created_at >= :since AND token != ''
            GROUP BY token ORDER BY max_score DESC LIMIT 20
        """)
        top_score_rows = (await session.execute(top_score_stmt, {"since": since})).fetchall()
        top_by_score = [{"token": r[0], "max_score": round(float(r[1]), 4), "count": r[2]} for r in top_score_rows]

        # Top 20 tokens by prediction count
        top_count_stmt = text("""
            SELECT token, COUNT(*) as cnt, MAX(predicted_score) as max_score
            FROM predictions WHERE created_at >= :since AND token != ''
            GROUP BY token ORDER BY cnt DESC LIMIT 20
        """)
        top_count_rows = (await session.execute(top_count_stmt, {"since": since})).fetchall()
        top_by_count = [{"token": r[0], "count": r[1], "max_score": round(float(r[2]), 4)} for r in top_count_rows]

        return {
            "prediction_count": pred_count,
            "avg_score": round(avg_score, 4),
            "score_buckets": buckets,
            "regime_distribution": regimes,
            "stage_distribution": stages,
            "top_by_score": top_by_score,
            "top_by_count": top_by_count,
        }
    except Exception as e:
        logger.error("scorecard.signal_activity.error", error=str(e)[:200])
        return {"prediction_count": 0, "avg_score": 0, "score_buckets": {},
                "regime_distribution": {}, "stage_distribution": {},
                "top_by_score": [], "top_by_count": [], "error": str(e)[:100]}


async def _candidate_filtering(session: AsyncSession, since: datetime) -> dict[str, Any]:
    """Section 3: Paper candidate filtering stats."""
    try:
        # Total paper_positions in window
        total_stmt = select(func.count()).select_from(PaperPosition).where(
            PaperPosition.created_at >= since
        )
        total = (await session.execute(total_stmt)).scalar() or 0

        # By status
        open_count = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.created_at >= since, PaperPosition.status == "OPEN")
        )).scalar() or 0

        closed_count = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.created_at >= since, PaperPosition.status == "CLOSED")
        )).scalar() or 0

        skipped_count = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.created_at >= since, PaperPosition.status == "SKIPPED")
        )).scalar() or 0

        # Skip reasons
        skip_reasons_stmt = text("""
            SELECT metadata_json->>'skip_reason' as reason, COUNT(*) as cnt
            FROM paper_positions
            WHERE created_at >= :since AND status = 'SKIPPED'
            AND metadata_json->>'skip_reason' IS NOT NULL
            GROUP BY reason ORDER BY cnt DESC
        """)
        skip_rows = (await session.execute(skip_reasons_stmt, {"since": since})).fetchall()
        skip_reasons = {row[0]: row[1] for row in skip_rows}

        return {
            "total_candidates": total,
            "opened": open_count,
            "closed": closed_count,
            "skipped": skipped_count,
            "skip_reasons": skip_reasons,
        }
    except Exception as e:
        logger.error("scorecard.candidate_filtering.error", error=str(e)[:200])
        return {"total_candidates": 0, "opened": 0, "closed": 0, "skipped": 0,
                "skip_reasons": {}, "error": str(e)[:100]}


async def _paper_trading_performance(session: AsyncSession, since: datetime) -> dict[str, Any]:
    """Section 4: Paper trading performance metrics."""
    try:
        # Position counts (all time, not just window — for portfolio state)
        open_now = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(PaperPosition.status == "OPEN")
        )).scalar() or 0

        # Closed in window
        closed_in_window = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.status == "CLOSED", PaperPosition.closed_at >= since)
        )).scalar() or 0

        # Opened in window
        opened_in_window = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.status == "OPEN", PaperPosition.created_at >= since)
        )).scalar() or 0

        # Skipped in window
        skipped_in_window = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.status == "SKIPPED", PaperPosition.created_at >= since)
        )).scalar() or 0

        # Outcome stats from paper_trade_outcomes
        outcomes_stmt = select(PaperTradeOutcome).where(PaperTradeOutcome.created_at >= since)
        outcomes_result = await session.execute(outcomes_stmt)
        outcomes = outcomes_result.scalars().all()

        rois = [o.roi for o in outcomes if o.roi is not None]
        pnls = [o.pnl_usd for o in outcomes if o.pnl_usd is not None]

        avg_roi = sum(rois) / len(rois) if rois else 0.0
        realized_pnl = sum(pnls) if pnls else 0.0

        # Best/worst trade
        best_roi = max(rois) if rois else 0.0
        worst_roi = min(rois) if rois else 0.0
        best_trade = None
        worst_trade = None
        for o in outcomes:
            if o.roi is not None and o.roi == best_roi:
                best_trade = {"token": o.token_mint, "roi": round(o.roi, 4), "pnl_usd": round(o.pnl_usd or 0, 4)}
            if o.roi is not None and o.roi == worst_roi:
                worst_trade = {"token": o.token_mint, "roi": round(o.roi, 4), "pnl_usd": round(o.pnl_usd or 0, 4)}

        # Max drawdown from outcomes
        max_dd = min(rois) if rois else 0.0

        # Latest snapshot
        snap_stmt = select(PaperPortfolioSnapshot).order_by(
            PaperPortfolioSnapshot.created_at.desc()
        ).limit(1)
        snap = (await session.execute(snap_stmt)).scalar_one_or_none()

        portfolio_value = snap.portfolio_value if snap else settings.PAPER_VIRTUAL_CAPITAL
        unrealized_pnl = snap.unrealized_pnl if snap else 0.0

        return {
            "positions_opened": opened_in_window,
            "positions_closed": closed_in_window,
            "open_positions": open_now,
            "skipped_positions": skipped_in_window,
            "avg_roi": round(avg_roi, 4),
            "realized_pnl": round(realized_pnl, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "portfolio_value": round(portfolio_value, 2),
            "max_drawdown": round(max_dd, 4),
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }
    except Exception as e:
        logger.error("scorecard.paper_trading.error", error=str(e)[:200])
        return {"positions_opened": 0, "positions_closed": 0, "open_positions": 0,
                "skipped_positions": 0, "avg_roi": 0, "realized_pnl": 0,
                "unrealized_pnl": 0, "portfolio_value": 0, "max_drawdown": 0,
                "best_trade": None, "worst_trade": None, "error": str(e)[:100]}


async def _outcome_quality(session: AsyncSession, since: datetime) -> dict[str, Any]:
    """Section 5: Outcome quality breakdown."""
    try:
        outcomes_stmt = select(PaperTradeOutcome).where(PaperTradeOutcome.created_at >= since)
        outcomes = (await session.execute(outcomes_stmt)).scalars().all()

        win = sum(1 for o in outcomes if o.outcome_status == "WIN")
        loss = sum(1 for o in outcomes if o.outcome_status == "LOSS")
        breakeven = sum(1 for o in outcomes if o.outcome_status == "BREAKEVEN")
        invalid = sum(1 for o in outcomes if o.outcome_status == "INVALID_CANDIDATE")
        timeout = sum(1 for o in outcomes if o.outcome_status == "TIMEOUT")
        stop_loss = sum(1 for o in outcomes if o.outcome_status == "STOP_LOSS")
        take_profit = sum(1 for o in outcomes if o.outcome_status in ("TAKE_PROFIT", "TAKE_PROFIT_1", "TAKE_PROFIT_2"))

        # Also count by exit_reason on positions
        sl_positions = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.closed_at >= since, PaperPosition.exit_reason == "STOP_LOSS")
        )).scalar() or 0

        tp_positions = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.closed_at >= since,
                PaperPosition.exit_reason.in_(["TAKE_PROFIT_1", "TAKE_PROFIT_2"]))
        )).scalar() or 0

        timeout_positions = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.closed_at >= since, PaperPosition.exit_reason == "TIMEOUT")
        )).scalar() or 0

        stale_positions = (await session.execute(
            select(func.count()).select_from(PaperPosition).where(
                PaperPosition.closed_at >= since, PaperPosition.exit_reason == "STALE_ACTIVITY")
        )).scalar() or 0

        return {
            "win": win,
            "loss": loss,
            "breakeven": breakeven,
            "invalid_candidate": invalid,
            "timeout": timeout_positions,
            "stop_loss": sl_positions,
            "take_profit": tp_positions,
            "stale_activity": stale_positions,
        }
    except Exception as e:
        logger.error("scorecard.outcome_quality.error", error=str(e)[:200])
        return {"win": 0, "loss": 0, "breakeven": 0, "invalid_candidate": 0,
                "timeout": 0, "stop_loss": 0, "take_profit": 0, "stale_activity": 0,
                "error": str(e)[:100]}


async def _system_health(session: AsyncSession) -> dict[str, Any]:
    """Section 6: System health metrics."""
    try:
        # DLQ count
        dlq_stmt = text("SELECT COUNT(*) FROM raw_events WHERE status = 'dead_letter'")
        dlq_count = (await session.execute(dlq_stmt)).scalar() or 0

        # Failed events
        failed_stmt = text("SELECT COUNT(*) FROM raw_events WHERE status = 'failed'")
        failed_count = (await session.execute(failed_stmt)).scalar() or 0

        # Events per hour (average over last 6 hours)
        eph_stmt = text("""
            SELECT COUNT(*) / GREATEST(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 3600, 1)
            FROM raw_events WHERE created_at > NOW() - INTERVAL '6 hours'
        """)
        events_per_hour = round(float((await session.execute(eph_stmt)).scalar() or 0), 1)

        # Helius provider info (from webhook manager)
        helius_info = _get_helius_info()

        return {
            "dlq_count": dlq_count,
            "failed_events": failed_count,
            "events_per_hour_avg": events_per_hour,
            "helius": helius_info,
        }
    except Exception as e:
        logger.error("scorecard.system_health.error", error=str(e)[:200])
        return {"dlq_count": 0, "failed_events": 0, "events_per_hour_avg": 0,
                "helius": {}, "error": str(e)[:100]}


def _get_helius_info() -> dict[str, Any]:
    """Get Helius provider info (non-DB, from webhook manager)."""
    try:
        from app.infrastructure.helius.webhook_manager import get_webhook_manager
        manager = get_webhook_manager()
        manager.reload()
        status = manager.get_status()
        providers = status.get("providers", [])
        available = sum(1 for p in providers if p.get("active") and not p.get("exhausted"))
        exhausted = sum(1 for p in providers if p.get("exhausted"))
        failovers = sum(1 for p in providers if p.get("last_failover_at"))
        return {
            "provider": status.get("active_provider", "none"),
            "health": status.get("health", "unknown"),
            "total_keys": len(providers),
            "available_keys": available,
            "exhausted_keys": exhausted,
            "failover_count": failovers,
        }
    except Exception:
        return {"provider": "unknown", "health": "unknown", "total_keys": 0,
                "available_keys": 0, "exhausted_keys": 0, "failover_count": 0}


# ── Verdict logic ───────────────────────────────────────────


def _compute_verdict(sections: dict[str, Any]) -> str:
    """Compute overall verdict: HEALTHY / WARNING / BROKEN."""
    pa = sections.get("pipeline_activity", {})
    sa = sections.get("signal_activity", {})
    sh = sections.get("system_health", {})
    pt = sections.get("paper_trading", {})

    # BROKEN: no events or predictions
    if pa.get("raw_events", 0) == 0:
        return "BROKEN"
    if pa.get("predictions", 0) == 0 and sa.get("prediction_count", 0) == 0:
        return "BROKEN"

    # BROKEN: DLQ growing or failed events high
    if sh.get("dlq_count", 0) > 100:
        return "BROKEN"
    if sh.get("failed_events", 0) > 500:
        return "BROKEN"

    # WARNING: various degradation signals
    warnings = 0
    if sa.get("prediction_count", 0) == 0 and pa.get("raw_events", 0) > 0:
        warnings += 1  # events flowing but no predictions
    if sh.get("dlq_count", 0) > 0:
        warnings += 1
    if sh.get("failed_events", 0) > 50:
        warnings += 1
    if pt.get("max_drawdown", 0) < -20:
        warnings += 1

    if warnings >= 2:
        return "WARNING"
    if warnings == 1:
        return "WARNING"

    return "HEALTHY"


def _recommended_action(sections: dict[str, Any]) -> str:
    """Generate recommended action based on scorecard."""
    verdict = sections.get("verdict", "UNKNOWN")
    pa = sections.get("pipeline_activity", {})
    sa = sections.get("signal_activity", {})
    pt = sections.get("paper_trading", {})
    cf = sections.get("candidate_filtering", {})

    if verdict == "BROKEN":
        if pa.get("raw_events", 0) == 0:
            return "fix_pipeline: no raw events — check Helius webhook and API keys"
        if pa.get("predictions", 0) == 0:
            return "fix_pipeline: events flowing but no predictions — check prediction worker"
        return "fix_pipeline: DLQ or failures growing — investigate worker errors"

    if verdict == "WARNING":
        if sa.get("prediction_count", 0) == 0:
            return "investigate: events active but predictions collapsed"
        if pt.get("max_drawdown", 0) < -20:
            return "tighten_filters: max drawdown exceeds -20%"
        return "keep_observing: minor degradation detected"

    # HEALTHY
    if pt.get("open_positions", 0) == 0 and cf.get("opened", 0) == 0:
        return "enable_next_paper_test: system healthy, no open positions"
    if pt.get("open_positions", 0) > 0:
        return "keep_observing: paper positions active, monitor ROI"
    return "keep_observing: system healthy"


# ── Markdown renderer ───────────────────────────────────────


def render_markdown(scorecard: dict[str, Any]) -> str:
    """Render scorecard as markdown report."""
    meta = scorecard.get("meta", {})
    hours = meta.get("window_hours", 24)
    pa = scorecard.get("pipeline_activity", {})
    sa = scorecard.get("signal_activity", {})
    cf = scorecard.get("candidate_filtering", {})
    pt = scorecard.get("paper_trading", {})
    oq = scorecard.get("outcome_quality", {})
    sh = scorecard.get("system_health", {})
    helius = sh.get("helius", {})
    verdict = scorecard.get("verdict", "UNKNOWN")
    action = scorecard.get("recommended_action", "")

    lines = []
    lines.append(f"# Daily Alpha Scorecard")
    lines.append(f"")
    lines.append(f"Window: last {hours}h")
    lines.append(f"Generated: {meta.get('generated_at', 'N/A')}")
    lines.append(f"")

    # System Activity
    lines.append(f"## System Activity")
    lines.append(f"")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Raw events | {pa.get('raw_events', 0):,} |")
    lines.append(f"| Wallet positions | {pa.get('wallet_positions', 0):,} |")
    lines.append(f"| Wallet metrics | {pa.get('wallet_metrics', 0):,} |")
    lines.append(f"| Wallet features | {pa.get('wallet_features', 0):,} |")
    lines.append(f"| Predictions | {pa.get('predictions', 0):,} |")
    lines.append(f"| Rankings | {pa.get('rankings', 0):,} |")
    lines.append(f"")

    # Prediction Quality
    lines.append(f"## Prediction Quality")
    lines.append(f"")
    lines.append(f"- Prediction count: **{sa.get('prediction_count', 0):,}**")
    lines.append(f"- Average score: **{sa.get('avg_score', 0):.4f}**")
    lines.append(f"")
    lines.append(f"### Score Distribution")
    lines.append(f"")
    lines.append(f"| Bucket | Count |")
    lines.append(f"|--------|-------|")
    buckets = sa.get("score_buckets", {})
    for label in ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]:
        lines.append(f"| {label} | {buckets.get(label, 0):,} |")
    lines.append(f"")

    # Regime distribution
    regimes = sa.get("regime_distribution", {})
    if regimes:
        lines.append(f"### Regime Distribution")
        lines.append(f"")
        for regime, cnt in list(regimes.items())[:5]:
            lines.append(f"- {regime}: {cnt:,}")
        lines.append(f"")

    # Stage distribution
    stages = sa.get("stage_distribution", {})
    if stages:
        lines.append(f"### Stage Distribution")
        lines.append(f"")
        for stage, cnt in list(stages.items())[:5]:
            lines.append(f"- {stage}: {cnt:,}")
        lines.append(f"")

    # Top tokens
    top_score = sa.get("top_by_score", [])
    if top_score:
        lines.append(f"### Top Tokens by Score")
        lines.append(f"")
        lines.append(f"| Token | Max Score | Predictions |")
        lines.append(f"|-------|-----------|-------------|")
        for t in top_score[:10]:
            lines.append(f"| `{t['token'][:12]}...` | {t['max_score']:.4f} | {t['count']:,} |")
        lines.append(f"")

    # Candidate Filtering
    lines.append(f"## Candidate Filtering")
    lines.append(f"")
    lines.append(f"- Total candidates: **{cf.get('total_candidates', 0):,}**")
    lines.append(f"- Opened: **{cf.get('opened', 0):,}**")
    lines.append(f"- Closed: **{cf.get('closed', 0):,}**")
    lines.append(f"- Skipped: **{cf.get('skipped', 0):,}**")
    lines.append(f"")
    skip_reasons = cf.get("skip_reasons", {})
    if skip_reasons:
        lines.append(f"### Skip Reasons")
        lines.append(f"")
        lines.append(f"| Reason | Count |")
        lines.append(f"|--------|-------|")
        for reason, cnt in skip_reasons.items():
            lines.append(f"| {reason} | {cnt:,} |")
        lines.append(f"")

    # Paper Trading
    lines.append(f"## Paper Trading")
    lines.append(f"")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Positions opened | {pt.get('positions_opened', 0):,} |")
    lines.append(f"| Positions closed | {pt.get('positions_closed', 0):,} |")
    lines.append(f"| Open positions | {pt.get('open_positions', 0):,} |")
    lines.append(f"| Skipped positions | {pt.get('skipped_positions', 0):,} |")
    lines.append(f"| Avg ROI | {pt.get('avg_roi', 0):.4f}% |")
    lines.append(f"| Realized PnL | ${pt.get('realized_pnl', 0):,.2f} |")
    lines.append(f"| Unrealized PnL | ${pt.get('unrealized_pnl', 0):,.2f} |")
    lines.append(f"| Portfolio value | ${pt.get('portfolio_value', 0):,.2f} |")
    lines.append(f"| Max drawdown | {pt.get('max_drawdown', 0):.4f}% |")
    lines.append(f"")

    best = pt.get("best_trade")
    worst = pt.get("worst_trade")
    if best:
        lines.append(f"- **Best trade**: `{best['token'][:12]}...` ROI {best['roi']:.2f}% / ${best['pnl_usd']:.2f}")
    if worst:
        lines.append(f"- **Worst trade**: `{worst['token'][:12]}...` ROI {worst['roi']:.2f}% / ${worst['pnl_usd']:.2f}")
    lines.append(f"")

    # Outcome Quality
    lines.append(f"## Outcome Quality")
    lines.append(f"")
    lines.append(f"| Outcome | Count |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Win | {oq.get('win', 0):,} |")
    lines.append(f"| Loss | {oq.get('loss', 0):,} |")
    lines.append(f"| Breakeven | {oq.get('breakeven', 0):,} |")
    lines.append(f"| Invalid candidate | {oq.get('invalid_candidate', 0):,} |")
    lines.append(f"| Timeout | {oq.get('timeout', 0):,} |")
    lines.append(f"| Stop loss | {oq.get('stop_loss', 0):,} |")
    lines.append(f"| Take profit | {oq.get('take_profit', 0):,} |")
    lines.append(f"| Stale activity | {oq.get('stale_activity', 0):,} |")
    lines.append(f"")

    # Health
    lines.append(f"## Health")
    lines.append(f"")
    lines.append(f"| Check | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| DLQ count | {sh.get('dlq_count', 0):,} |")
    lines.append(f"| Failed events | {sh.get('failed_events', 0):,} |")
    lines.append(f"| Events/hour avg | {sh.get('events_per_hour_avg', 0):,.1f} |")
    lines.append(f"| Helius provider | {helius.get('provider', 'N/A')} |")
    lines.append(f"| Helius health | {helius.get('health', 'N/A')} |")
    lines.append(f"| Available keys | {helius.get('available_keys', 0)}/{helius.get('total_keys', 0)} |")
    lines.append(f"| Exhausted keys | {helius.get('exhausted_keys', 0)} |")
    lines.append(f"| Failover count | {helius.get('failover_count', 0)} |")
    lines.append(f"")

    # Verdict
    lines.append(f"## Verdict")
    lines.append(f"")
    lines.append(f"**{verdict}**")
    lines.append(f"")

    # Recommended Action
    lines.append(f"## Recommended Action")
    lines.append(f"")
    lines.append(f"- {action}")
    lines.append(f"")

    return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────


async def _count_since(
    session: AsyncSession,
    model: Any,
    column: Any,
    since: datetime,
) -> int:
    """Count rows in model where column >= since."""
    stmt = select(func.count()).select_from(model).where(column >= since)
    return (await session.execute(stmt)).scalar() or 0
