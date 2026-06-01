"""Dashboard endpoint — monitoring web UI with alerts."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    finally:
        await session.close()

    # Get compact Helius card data
    helius = _get_helius_mini_data(seconds_ago, events_last_hour, events_5m_count)

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
        .top-bar-right {{ flex: 0 0 auto; }}

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
            .helius-mini {{ width: 100%; }}
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
    html += f"""            </tbody>
        </table>
    </div>

    <div class="footer">
        <p>Workers: 9 Active | Webhook: {webhook_status.upper()} | Helius: Free Plan</p>
        <p>Last refresh: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    </div>
</body>
</html>"""

    return html
