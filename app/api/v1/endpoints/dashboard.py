"""Dashboard endpoint — monitoring web UI with alerts."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.infrastructure.database.models.paper_trading import (
    PaperPortfolioSnapshot,
    PaperPosition,
    PaperTradeOutcome,
)
from app.infrastructure.helius.webhook_manager import get_webhook_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_helius_mini_data(seconds_ago: int, events_last_hour: int, events_5m: int) -> dict:
    """Get compact Helius provider data for dashboard mini card."""
    try:
        manager = get_webhook_manager()
        manager.reload()
        status = manager.get_status()

        # Count available and exhausted keys
        available = sum(
            1 for p in status["providers"]
            if p.get("active") and not p.get("exhausted")
        )
        total = len(status["providers"])
        exhausted = sum(
            1 for p in status["providers"]
            if p.get("exhausted")
        )

        # Count failovers from persisted provider state
        failover_count = sum(
            1 for p in status["providers"]
            if p.get("last_failover_at")
        )

        # Health
        health = status.get("health", "unknown")

        # Color based on global last event age (from DB, not provider)
        if health in ("exhausted", "error"):
            color = "red"
        elif seconds_ago < 300:
            color = "green"
        elif seconds_ago < 1800:
            color = "yellow"
        else:
            color = "red"

        return {
            "provider": status.get("active_provider") or "none",
            "health": health,
            "color": color,
            "events_last_hour": events_last_hour,
            "events_5m": events_5m,
            "last_event_age": _format_age_short(seconds_ago),
            "last_color": "green" if seconds_ago < 300 else "yellow" if seconds_ago < 1800 else "red",
            "failover_count": failover_count,
            "available_keys": available,
            "total_keys": total,
            "exhausted_keys": exhausted,
            "multi_webhook": status.get("multi_webhook_mode", False),
        }
    except Exception as e:
        logger.error("helius_mini.error", error=str(e))
        return {
            "provider": "error",
            "health": "error",
            "color": "red",
            "events_last_hour": 0,
            "events_5m": 0,
            "last_event_age": "error",
            "last_color": "red",
            "failover_count": 0,
            "available_keys": 0,
            "total_keys": 0,
            "exhausted_keys": 0,
            "multi_webhook": False,
        }


def _format_age_short(seconds: int) -> str:
    """Short age format: 0s, 18s, 3m, 1h."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


async def _get_vps_health(request: Request) -> dict:
    """Get VPS system health metrics using psutil.

    Returns safe aggregate metrics only — no secrets, no private paths.
    """
    result = {
        "cpu_percent": 0.0,
        "memory": {"used_gb": 0, "total_gb": 0, "percent": 0.0},
        "disk": {"used_gb": 0, "total_gb": 0, "percent": 0.0},
        "load_avg": [0.0, 0.0, 0.0],
        "uptime_seconds": 0,
        "redis": {"used_mb": 0, "max_mb": 0, "percent": 0.0},
        "postgres": {"database_size_mb": 0},
        "containers": {"api": "unknown", "worker": "unknown", "postgres": "unknown", "redis": "unknown"},
    }

    # CPU, memory, disk, uptime via psutil
    try:
        import psutil
        result["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        result["memory"] = {
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "percent": mem.percent,
        }
        disk = psutil.disk_usage("/")
        result["disk"] = {
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "total_gb": round(disk.total / (1024 ** 3), 1),
            "percent": round(disk.percent, 1),
        }
        load = psutil.getloadavg()
        result["load_avg"] = [round(l, 2) for l in load]
        result["uptime_seconds"] = int(time.time() - psutil.boot_time())
    except ImportError:
        pass
    except Exception:
        pass

    # Redis memory
    try:
        redis_manager = getattr(request.app.state, "redis_manager", None)
        if redis_manager:
            client = redis_manager.get_client("default")
            if client:
                info = await client.info("memory")
                used = info.get("used_memory", 0)
                maxmem = info.get("maxmemory", 0)
                result["redis"] = {
                    "used_mb": round(used / (1024 ** 2)),
                    "max_mb": round(maxmem / (1024 ** 2)),
                    "percent": round(used / maxmem * 100, 1) if maxmem > 0 else 0.0,
                }
    except Exception:
        pass

    # PostgreSQL database size
    try:
        db_manager = getattr(request.app.state, "db_manager", None)
        if db_manager:
            session = db_manager.get_session()
            try:
                res = await session.execute(text("SELECT pg_database_size(current_database())"))
                size_bytes = res.scalar() or 0
                result["postgres"] = {"database_size_mb": round(size_bytes / (1024 ** 2))}
            finally:
                await session.close()
    except Exception:
        pass

    # Container health (check connectivity from API container)
    try:
        # API is healthy if we're responding
        result["containers"]["api"] = "healthy"

        # Redis health via ping
        redis_manager = getattr(request.app.state, "redis_manager", None)
        if redis_manager:
            client = redis_manager.get_client("default")
            if client:
                await client.ping()
                result["containers"]["redis"] = "healthy"
            else:
                result["containers"]["redis"] = "unhealthy"
        else:
            result["containers"]["redis"] = "unknown"

        # Postgres health via query
        db_manager = getattr(request.app.state, "db_manager", None)
        if db_manager:
            session = db_manager.get_session()
            try:
                await session.execute(text("SELECT 1"))
                result["containers"]["postgres"] = "healthy"
            finally:
                await session.close()
        else:
            result["containers"]["postgres"] = "unknown"

        # Worker health — check if recent predictions exist (proxy for worker liveness)
        if db_manager:
            session = db_manager.get_session()
            try:
                res = await session.execute(text(
                    "SELECT COUNT(*) FROM predictions WHERE created_at > NOW() - INTERVAL '5 minutes'"
                ))
                count = res.scalar() or 0
                result["containers"]["worker"] = "healthy" if count > 0 else "unhealthy"
            finally:
                await session.close()
    except Exception:
        pass

    return result


def _vps_health_color(percent: float, warn: float = 70, crit: float = 90) -> str:
    """Return color hex for a percentage metric."""
    if percent >= crit:
        return "#ff4444"
    if percent >= warn:
        return "#ffaa00"
    return "#00ff88"


def _vps_container_color(containers: dict[str, str]) -> str:
    """Return color for container health summary."""
    statuses = list(containers.values())
    if any(s in ("dead", "exited") for s in statuses):
        return "#ff4444"
    if any(s in ("unhealthy", "restarting") for s in statuses):
        return "#ffaa00"
    if all(s == "healthy" for s in statuses):
        return "#00ff88"
    return "#ffaa00"


def _format_uptime(seconds: int) -> str:
    """Format uptime seconds to human-readable."""
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    return f"{days}d {hours}h"


async def _get_paper_mini_data(session: AsyncSession) -> dict:
    """Get compact paper trading data for dashboard mini card."""
    try:
        # Position counts
        open_count = (
            await session.execute(
                select(func.count()).select_from(PaperPosition).where(
                    PaperPosition.status == "OPEN"
                )
            )
        ).scalar() or 0

        # Realized PnL from closed outcomes
        realized_pnl = float(
            (await session.execute(
                select(func.coalesce(func.sum(PaperTradeOutcome.pnl_usd), 0.0))
            )).scalar() or 0.0
        )

        # Open positions with metadata
        open_positions = []
        if open_count > 0:
            result = await session.execute(
                select(PaperPosition)
                .where(PaperPosition.status == "OPEN")
                .order_by(PaperPosition.created_at.desc())
                .limit(3)
            )
            for pos in result.scalars().all():
                meta = pos.metadata_json or {}
                entry_price = pos.entry_price or 0
                current_price = meta.get("current_price", 0)
                current_roi = meta.get("current_roi", 0)
                max_return = meta.get("max_return", 0)
                max_drawdown = meta.get("max_drawdown", 0)
                virtual_size = pos.virtual_size_usd or 0
                unrealized_pnl = virtual_size * (current_roi / 100) if current_roi else 0

                open_positions.append({
                    "token_short": f"{pos.token_mint[:4]}...{pos.token_mint[-4:]}" if len(pos.token_mint) > 8 else pos.token_mint,
                    "token_mint": pos.token_mint,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "current_roi": round(current_roi, 2),
                    "max_return": round(max_return, 2),
                    "max_drawdown": round(max_drawdown, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "virtual_size_usd": virtual_size,
                    "rank": meta.get("rank", 0),
                    "entry_score": pos.entry_score,
                    "regime": meta.get("regime", ""),
                    "stage": meta.get("stage", ""),
                    "opened_at": pos.opened_at.isoformat() if pos.opened_at else "",
                })

        # Unrealized PnL from open positions
        total_unrealized = sum(p["unrealized_pnl"] for p in open_positions)

        # Latest snapshot
        snap_result = await session.execute(
            select(PaperPortfolioSnapshot)
            .order_by(PaperPortfolioSnapshot.created_at.desc())
            .limit(1)
        )
        last_snap = snap_result.scalar_one_or_none()
        last_snap_time = last_snap.created_at.isoformat() if last_snap and last_snap.created_at else None

        # Mode determination
        if not settings.PAPER_TRADING_ENABLED:
            mode = "DISABLED"
            mode_color = "gray"
        elif settings.PAPER_TRADING_DRY_RUN:
            mode = "DRY RUN"
            mode_color = "yellow"
        else:
            mode = "ENABLED"
            mode_color = "green"

        # PnL color
        total_pnl = total_unrealized + realized_pnl
        if total_pnl > 0:
            pnl_color = "#00ff88"
            pnl_sign = "+"
        elif total_pnl < 0:
            pnl_color = "#ff4444"
            pnl_sign = "-"
        else:
            pnl_color = "#888"
            pnl_sign = ""

        virtual_capital = settings.PAPER_VIRTUAL_CAPITAL
        portfolio_value = virtual_capital + total_pnl

        return {
            "mode": mode,
            "mode_color": mode_color,
            "open_count": open_count,
            "portfolio_value": round(portfolio_value, 2),
            "virtual_capital": virtual_capital,
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(realized_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "pnl_sign": pnl_sign,
            "pnl_color": pnl_color,
            "positions": open_positions,
            "last_snapshot": last_snap_time,
        }

    except Exception as e:
        logger.error("paper_mini.error", error=str(e))
        return {
            "mode": "ERROR",
            "mode_color": "red",
            "open_count": 0,
            "portfolio_value": 0,
            "virtual_capital": 0,
            "unrealized_pnl": 0,
            "realized_pnl": 0,
            "total_pnl": 0,
            "pnl_sign": "",
            "pnl_color": "#888",
            "positions": [],
            "last_snapshot": None,
        }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> str:
    """Monitoring dashboard with webhook health alerts."""
    db_manager = request.app.state.db_manager
    session: AsyncSession = db_manager.get_session()

    try:
        # Database counts
        raw_count = (await session.execute(text("SELECT COUNT(*) FROM raw_events"))).scalar() or 0
        pos_count = (await session.execute(text("SELECT COUNT(*) FROM wallet_positions"))).scalar() or 0
        metrics_count = (await session.execute(text("SELECT COUNT(*) FROM wallet_metrics"))).scalar() or 0
        features_count = (await session.execute(text("SELECT COUNT(*) FROM wallet_features"))).scalar() or 0
        pred_count = (await session.execute(text("SELECT COUNT(*) FROM predictions"))).scalar() or 0

        # Last event info
        last_event = (await session.execute(text("SELECT event_type, created_at, status FROM raw_events ORDER BY created_at DESC LIMIT 1"))).first()
        last_event_type = last_event[0] if last_event else "N/A"
        last_event_dt = last_event[1] if last_event else None
        last_event_status = last_event[2] if last_event else "N/A"

        # Calculate time since last event
        now = datetime.now(timezone.utc)
        if last_event_dt:
            if last_event_dt.tzinfo is None:
                last_event_dt = last_event_dt.replace(tzinfo=timezone.utc)
            seconds_ago = int((now - last_event_dt).total_seconds())
            if seconds_ago < 60:
                time_ago = f"{seconds_ago}s ago"
            elif seconds_ago < 3600:
                time_ago = f"{seconds_ago // 60}m {seconds_ago % 60}s ago"
            elif seconds_ago < 86400:
                time_ago = f"{seconds_ago // 3600}h {(seconds_ago % 3600) // 60}m ago"
            else:
                time_ago = f"{seconds_ago // 86400}d ago"
        else:
            seconds_ago = 999999
            time_ago = "No events"

        # Webhook health status
        if seconds_ago < 300:  # < 5 minutes
            webhook_status = "healthy"
            webhook_color = "#00ff88"
            webhook_text = "ACTIVE - Receiving events"
        elif seconds_ago < 1800:  # < 30 minutes
            webhook_status = "warning"
            webhook_color = "#ffaa00"
            webhook_text = "SLOW - No events for " + time_ago
        else:
            webhook_status = "critical"
            webhook_color = "#ff4444"
            webhook_text = "DOWN - No events for " + time_ago

        # Events per hour (last hour)
        events_last_hour = (await session.execute(text(
            "SELECT COUNT(*) FROM raw_events WHERE created_at > NOW() - INTERVAL '1 hour'"
        ))).scalar() or 0

        # Events last 5 min
        events_5m_count = (await session.execute(text(
            "SELECT COUNT(*) FROM raw_events WHERE created_at > NOW() - INTERVAL '5 minutes'"
        ))).scalar() or 0

        # Recent events
        recent = (await session.execute(text(
            "SELECT event_type, status, created_at FROM raw_events ORDER BY created_at DESC LIMIT 10"
        ))).all()

        # Events per 5 min (for mini chart)
        events_5m = []
        for i in range(12):
            start = now - timedelta(minutes=5 * (i + 1))
            end = now - timedelta(minutes=5 * i)
            count = (await session.execute(text(
                "SELECT COUNT(*) FROM raw_events WHERE created_at > :start AND created_at <= :end"
            ), {"start": start, "end": end})).scalar() or 0
            events_5m.append(count)
        events_5m.reverse()

        # Paper trading card data
        paper = await _get_paper_mini_data(session)

    except Exception as e:
        raw_count = pos_count = metrics_count = features_count = pred_count = 0
        last_event_type = "ERROR"
        time_ago = str(e)[:50]
        seconds_ago = 999999
        webhook_status = "error"
        webhook_color = "#ff4444"
        webhook_text = f"ERROR: {str(e)[:50]}"
        events_last_hour = 0
        events_5m_count = 0
        last_event_status = "N/A"
        recent = []
        events_5m = [0] * 12
        paper = {"mode": "ERROR", "mode_color": "red", "open_count": 0, "portfolio_value": 0, "virtual_capital": 0, "unrealized_pnl": 0, "realized_pnl": 0, "total_pnl": 0, "pnl_sign": "", "pnl_color": "#888", "positions": [], "last_snapshot": None}
    finally:
        await session.close()

    # Get compact Helius card data
    helius = _get_helius_mini_data(seconds_ago, events_last_hour, events_5m_count)

    # Build paper trading card HTML
    paper_pos_html = ""
    if paper["positions"]:
        paper_pos_html = '<div class="paper-pos">'
        for pos in paper["positions"][:3]:
            roi_color = "#00ff88" if pos["current_roi"] > 0 else "#ff4444" if pos["current_roi"] < 0 else "#888"
            roi_sign = "+" if pos["current_roi"] > 0 else ""
            paper_pos_html += f'<div class="paper-pos-line"><span class="paper-pos-token">{pos["token_short"]}</span><span class="paper-pos-roi" style="color: {roi_color}">{roi_sign}{pos["current_roi"]}%</span><span class="paper-pos-detail">Score {pos["entry_score"]:.2f} &middot; Rank {pos["rank"]}</span></div>'
            paper_pos_html += f'<div class="paper-pos-line"><span class="paper-pos-detail">{pos["regime"]} / {pos["stage"]}</span></div>'
        paper_pos_html += '</div>'
    else:
        paper_pos_html = '<div class="paper-pos"><div class="paper-pos-line"><span class="paper-pos-detail">No open positions</span></div></div>'

    # Get VPS health data
    vps = await _get_vps_health(request)

    # Build alert banner
    if webhook_status == "critical":
        alert_html = f'''
        <div class="alert critical">
            <span class="alert-icon">!</span>
            <div>
                <strong>WEBHOOK DOWN</strong> - No events received for {time_ago}<br>
                <small>Kemungkinan: Helius credit habis, webhook disabled, atau tidak ada aktivitas Solana</small>
            </div>
        </div>'''
    elif webhook_status == "warning":
        alert_html = f'''
        <div class="alert warning">
            <span class="alert-icon">!</span>
            <div>
                <strong>WEBHOOK SLOW</strong> - Last event {time_ago}<br>
                    <small>Monitor jika tidak ada event dalam 30 menit</small>
            </div>
        </div>'''
    else:
        alert_html = ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Solana Wallet Intel - Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f23; color: #e0e0e0; padding: 20px; }}

        .top-bar {{ display: flex; align-items: flex-start; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }}
        .top-bar-left {{ flex: 1; min-width: 300px; }}
        .top-bar-right {{ flex: 0 0 auto; display: flex; gap: 12px; flex-wrap: wrap; }}

        .header {{ padding: 10px 0; }}
        .header h1 {{ color: #00ff88; font-size: 22px; }}
        .header p {{ color: #888; margin-top: 3px; font-size: 12px; }}

        .alert {{ display: flex; align-items: center; gap: 15px; padding: 12px 16px; border-radius: 10px; margin-bottom: 15px; border: 1px solid; }}
        .alert.critical {{ background: #ff444422; border-color: #ff4444; }}
        .alert.warning {{ background: #ffaa0022; border-color: #ffaa00; }}
        .alert-icon {{ font-size: 20px; font-weight: bold; }}
        .alert.critical .alert-icon {{ color: #ff4444; }}
        .alert.warning .alert-icon {{ color: #ffaa00; }}

        .webhook-status {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: #1a1a2e; border-radius: 10px; border: 1px solid #333; }}
        .status-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
        .status-dot.healthy {{ background: #00ff88; box-shadow: 0 0 8px #00ff88; animation: pulse 2s infinite; }}
        .status-dot.warning {{ background: #ffaa00; box-shadow: 0 0 8px #ffaa00; animation: pulse 1s infinite; }}
        .status-dot.critical {{ background: #ff4444; box-shadow: 0 0 8px #ff4444; animation: pulse 0.5s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

        .helius-mini {{ background: #1a1a2e; border: 1px solid #333; border-radius: 10px; padding: 12px 14px; width: 260px; font-size: 12px; }}
        .helius-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .helius-row strong {{ color: #e0e0e0; font-size: 13px; }}
        .helius-row .provider {{ color: #00ff88; font-size: 12px; margin-left: auto; }}
        .helius-mini-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }}
        .helius-mini-grid div {{ color: #888; }}
        .helius-mini-grid b {{ color: #e0e0e0; font-weight: 600; }}
        .helius-footer {{ margin-top: 8px; padding-top: 6px; border-top: 1px solid #333; color: #555; font-size: 11px; }}

        .paper-mini {{ background: #1a1a2e; border: 1px solid #333; border-radius: 10px; padding: 12px 14px; width: 280px; font-size: 12px; }}
        .paper-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .paper-row strong {{ color: #e0e0e0; font-size: 13px; }}
        .paper-mode {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; margin-left: auto; }}
        .paper-mode.green {{ background: #00ff8822; color: #00ff88; }}
        .paper-mode.yellow {{ background: #ffaa0022; color: #ffaa00; }}
        .paper-mode.gray {{ background: #88888822; color: #888; }}
        .paper-mode.red {{ background: #ff444422; color: #ff4444; }}
        .paper-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }}
        .paper-stats div {{ color: #888; }}
        .paper-stats b {{ color: #e0e0e0; font-weight: 600; }}
        .paper-pos {{ margin-top: 8px; padding-top: 6px; border-top: 1px solid #333; }}
        .paper-pos-line {{ display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }}
        .paper-pos-token {{ color: #00aaff; font-family: monospace; font-size: 11px; }}
        .paper-pos-roi {{ font-weight: 600; font-size: 11px; }}
        .paper-pos-detail {{ color: #666; font-size: 10px; }}
        .paper-footer {{ margin-top: 8px; padding-top: 6px; border-top: 1px solid #333; color: #555; font-size: 11px; }}

        .vps-mini {{ background: #1a1a2e; border: 1px solid #333; border-radius: 10px; padding: 12px 14px; width: 280px; font-size: 12px; }}
        .vps-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .vps-row strong {{ color: #e0e0e0; font-size: 13px; }}
        .vps-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }}
        .vps-grid div {{ color: #888; }}
        .vps-grid b {{ color: #e0e0e0; font-weight: 600; }}
        .vps-containers {{ margin-top: 8px; padding-top: 6px; border-top: 1px solid #333; display: flex; gap: 6px; flex-wrap: wrap; }}
        .vps-ctag {{ font-size: 10px; padding: 2px 5px; border-radius: 3px; }}
        .vps-ctag.healthy {{ background: #00ff8822; color: #00ff88; }}
        .vps-ctag.unhealthy {{ background: #ff444422; color: #ff4444; }}
        .vps-ctag.starting {{ background: #ffaa0022; color: #ffaa00; }}
        .vps-ctag.unknown {{ background: #88888822; color: #888; }}
        .vps-footer {{ margin-top: 8px; padding-top: 6px; border-top: 1px solid #333; color: #555; font-size: 11px; }}

        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 15px; }}
        .card {{ background: #1a1a2e; border-radius: 10px; padding: 14px; border: 1px solid #333; }}
        .card h3 {{ color: #888; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
        .card .value {{ font-size: 26px; font-weight: bold; }}
        .card .value.green {{ color: #00ff88; }}
        .card .value.blue {{ color: #00aaff; }}
        .card .value.yellow {{ color: #ffaa00; }}
        .card .value.red {{ color: #ff4444; }}
        .card .sub {{ color: #666; font-size: 11px; margin-top: 3px; }}

        .section {{ background: #1a1a2e; border-radius: 10px; padding: 16px; border: 1px solid #333; margin-bottom: 15px; }}
        .section h2 {{ color: #00ff88; font-size: 14px; margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; color: #888; font-size: 11px; text-transform: uppercase; padding: 8px; border-bottom: 1px solid #333; }}
        td {{ padding: 6px 8px; border-bottom: 1px solid #222; font-size: 12px; }}
        tr:hover {{ background: #222; }}
        .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; }}
        .badge.completed {{ background: #00ff8822; color: #00ff88; }}
        .badge.processing {{ background: #00aaff22; color: #00aaff; }}
        .badge.pending {{ background: #ffaa0022; color: #ffaa00; }}

        .chart {{ display: flex; align-items: flex-end; gap: 3px; height: 50px; margin-top: 8px; }}
        .chart-bar {{ flex: 1; background: #00ff8844; border-radius: 2px 2px 0 0; min-height: 2px; transition: height 0.3s; }}
        .chart-bar:hover {{ background: #00ff88; }}
        .chart-label {{ display: flex; justify-content: space-between; color: #555; font-size: 10px; margin-top: 4px; }}

        .footer {{ text-align: center; color: #555; font-size: 11px; margin-top: 15px; }}

        @media (max-width: 600px) {{
            .top-bar {{ flex-direction: column; }}
            .top-bar-right {{ width: 100%; }}
            .helius-mini, .paper-mini, .vps-mini {{ width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="top-bar">
        <div class="top-bar-left">
            <div class="header">
                <h1>Solana Wallet Intel</h1>
                <p>Real-time Intelligence Dashboard | Auto-refresh: 30s</p>
            </div>
            {alert_html}
            <div class="webhook-status">
                <div class="status-dot {webhook_status}"></div>
                <div>
                    <strong>Webhook: {webhook_text}</strong><br>
                    <small>Last event: {last_event_type} | {time_ago} | Events/hour: {events_last_hour:,}</small>
                </div>
            </div>
        </div>
        <div class="top-bar-right">
            <div class="helius-mini">
                <div class="helius-row">
                    <span class="status-dot {helius['color']}"></span>
                    <strong>Helius</strong>
                    <span class="provider">{helius['provider']}</span>
                </div>
                <div class="helius-mini-grid">
                    <div>Events/hr <b>{helius['events_last_hour']:,}</b></div>
                    <div>5m <b>{helius['events_5m']:,}</b></div>
                    <div>Last <b style="color: #{'00ff88' if helius['last_color'] == 'green' else 'ffaa00' if helius['last_color'] == 'yellow' else 'ff4444'}">{helius['last_event_age']}</b></div>
                    <div>Keys <b>{helius['available_keys']}/{helius['total_keys']}</b></div>
                </div>
                <div class="helius-footer">
                    Failovers: {helius['failover_count']} &middot; Multi: {'On' if helius['multi_webhook'] else 'Off'}
                </div>
            </div>
            <div class="paper-mini">
                <div class="paper-row">
                    <strong>Paper Trading</strong>
                    <span class="paper-mode {paper['mode_color']}">{paper['mode']}</span>
                </div>
                <div class="paper-stats">
                    <div>Open <b>{paper['open_count']}</b></div>
                    <div>Portfolio <b>${paper['portfolio_value']:,.2f}</b></div>
                    <div>PnL <b style="color: {paper['pnl_color']}">{paper['pnl_sign']}${abs(paper['total_pnl']):,.2f}</b></div>
                    <div>Realized <b>${paper['realized_pnl']:,.2f}</b></div>
                </div>
                {paper_pos_html}
                <div class="paper-footer">
                    Capital: ${paper['virtual_capital']:,.0f} &middot; Unrealized: {paper['pnl_sign']}${abs(paper['unrealized_pnl']):,.2f}
                </div>
            </div>
            <div class="vps-mini">
                <div class="vps-row">
                    <strong>VPS Health</strong>
                    <span style="color: {_vps_container_color(vps['containers'])}; font-size: 10px; margin-left: auto;">{sum(1 for s in vps['containers'].values() if s == 'healthy')}/{len(vps['containers'])} healthy</span>
                </div>
                <div class="vps-grid">
                    <div>CPU <b style="color: {_vps_health_color(vps['cpu_percent'])}">{vps['cpu_percent']:.0f}%</b></div>
                    <div>RAM <b style="color: {_vps_health_color(vps['memory']['percent'])}">{vps['memory']['percent']:.0f}%</b></div>
                    <div>Disk <b style="color: {_vps_health_color(vps['disk']['percent'], 70, 85)}">{vps['disk']['percent']:.0f}%</b></div>
                    <div>Redis <b style="color: {_vps_health_color(vps['redis']['percent'])}">{vps['redis']['percent']:.0f}%</b></div>
                    <div>Load <b>{vps['load_avg'][0]:.2f}</b></div>
                    <div>DB <b>{vps['postgres']['database_size_mb'] / 1024:.1f}GB</b></div>
                </div>
                <div class="vps-containers">
                    <span class="vps-ctag {vps['containers']['api']}">api</span>
                    <span class="vps-ctag {vps['containers']['worker']}">worker</span>
                    <span class="vps-ctag {vps['containers']['postgres']}">postgres</span>
                    <span class="vps-ctag {vps['containers']['redis']}">redis</span>
                </div>
                <div class="vps-footer">
                    Uptime: {_format_uptime(vps['uptime_seconds'])} &middot; RAM {vps['memory']['used_gb']}/{vps['memory']['total_gb']}GB &middot; Disk {vps['disk']['used_gb']}/{vps['disk']['total_gb']}GB
                </div>
            </div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Raw Events</h3>
            <div class="value green">{raw_count:,}</div>
            <div class="sub">+{events_last_hour} last hour</div>
        </div>
        <div class="card">
            <h3>Positions</h3>
            <div class="value blue">{pos_count:,}</div>
        </div>
        <div class="card">
            <h3>Metrics</h3>
            <div class="value yellow">{metrics_count:,}</div>
        </div>
        <div class="card">
            <h3>Features</h3>
            <div class="value blue">{features_count:,}</div>
        </div>
        <div class="card">
            <h3>Predictions</h3>
            <div class="value green">{pred_count:,}</div>
        </div>
    </div>

    <div class="section">
        <h2>Events (Last Hour)</h2>
        <div class="chart">
"""
    max_val = max(events_5m) if events_5m else 1
    for i, count in enumerate(events_5m):
        height = max(2, int((count / max_val) * 45)) if max_val > 0 else 2
        html += f'            <div class="chart-bar" style="height:{height}px" title="{count} events"></div>\n'

    html += f"""        </div>
        <div class="chart-label">
            <span>-60m</span>
            <span>-30m</span>
            <span>Now</span>
        </div>
    </div>

    <div class="section">
        <h2>Recent Events</h2>
        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
"""
    for event in recent:
        etype = event[0] or "N/A"
        estatus = event[1] or "N/A"
        etime = event[2].strftime("%H:%M:%S") if event[2] else "N/A"
        badge_class = estatus.lower() if estatus.lower() in ["completed", "processing", "pending"] else "pending"
        html += f"""                <tr>
                    <td>{etype}</td>
                    <td><span class="badge {badge_class}">{estatus}</span></td>
                    <td>{etime}</td>
                </tr>
"""
    # Redis memory health
    redis_mem = await _get_redis_memory(request)

    html += f"""            </tbody>
        </table>
    </div>

    <div class="footer">
        <p>Workers: 9 Active | Webhook: {webhook_status.upper()} | Redis: {redis_mem} | Helius: Free Plan</p>
        <p>Last refresh: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    </div>
</body>
</html>"""

    return html


async def _get_redis_memory(request: Request) -> str:
    """Get Redis memory usage percentage for footer display."""
    try:
        redis_manager = getattr(request.app.state, "redis_manager", None)
        if not redis_manager:
            return "N/A"
        client = redis_manager.get_client("default")
        if client is None:
            return "N/A"
        info = await client.info("memory")
        used = info.get("used_memory", 0)
        maxmem = info.get("maxmemory", 0)
        if maxmem > 0:
            pct = round(used / maxmem * 100, 1)
            color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
            return f"Mem {pct}%"
        return f"Mem {used // (1024*1024)}MB"
    except Exception:
        return "Redis ERR"
