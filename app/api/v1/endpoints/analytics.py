"""Analytics endpoints — daily scorecard and reports."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.analytics.daily_scorecard import generate_scorecard, render_markdown
from app.infrastructure.database.session import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/daily-scorecard",
    summary="Daily alpha scorecard",
)
async def daily_scorecard(
    hours: int = Query(default=24, ge=1, le=168, description="Lookback window in hours"),
    format: str = Query(default="json", description="Response format: json or markdown"),
) -> Any:
    """Generate a daily alpha scorecard report.

    Returns comprehensive analytics covering:
    - Pipeline activity
    - Signal quality and prediction distribution
    - Candidate filtering and skip reasons
    - Paper trading performance
    - Outcome quality (win/loss/breakeven)
    - System health (DLQ, Redis, Helius)
    - Verdict and recommended action
    """
    async with async_session_factory() as session:
        scorecard = await generate_scorecard(session, hours=hours)

    if format == "markdown":
        md = render_markdown(scorecard)
        return PlainTextResponse(content=md, media_type="text/plain")

    return scorecard
