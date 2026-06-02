"""Generate daily alpha scorecard — CLI tool.

Usage:
    python scripts/generate_daily_scorecard.py [--hours 24]

Prints markdown report to terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.analytics.daily_scorecard import generate_scorecard, render_markdown
from app.infrastructure.database.session import async_session_factory


async def main(hours: int) -> None:
    async with async_session_factory() as session:
        scorecard = await generate_scorecard(session, hours=hours)
    md = render_markdown(scorecard)
    print(md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate daily alpha scorecard")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    args = parser.parse_args()
    asyncio.run(main(args.hours))
