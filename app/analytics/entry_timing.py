"""Entry timing metrics — analyze price action around paper trade entries.

Uses historical price snapshots to compute:
- Price at entry time and at offsets (5m, 15m, 30m, 60m before)
- Local low within 60m window
- Distance from local low
- Price change percentages at various windows
- Data quality indicator

Safety:
- Returns "insufficient_history" when not enough snapshots exist
- Never raises on missing data
- All prices default to None when unavailable
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.token_price_snapshot import TokenPriceSnapshot
from app.infrastructure.database.repositories.price_snapshot_repo import (
    PriceSnapshotRepository,
)

logger = structlog.get_logger(__name__)

# Minimum snapshots needed in a window to consider it sufficient
MIN_SNAPSHOTS_FOR_METRICS = 4


class EntryTimingMetrics:
    """Computed entry timing metrics for a paper trade."""

    def __init__(
        self,
        token_mint: str,
        entry_time: datetime,
        entry_price: float | None,
        price_5m_before: float | None,
        price_15m_before: float | None,
        price_30m_before: float | None,
        price_60m_before: float | None,
        local_low_60m: float | None,
        entry_distance_from_local_low_pct: float | None,
        price_change_15m_pct: float | None,
        price_change_30m_pct: float | None,
        price_change_60m_pct: float | None,
        data_quality: str,
    ) -> None:
        self.token_mint = token_mint
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.price_5m_before = price_5m_before
        self.price_15m_before = price_15m_before
        self.price_30m_before = price_30m_before
        self.price_60m_before = price_60m_before
        self.local_low_60m = local_low_60m
        self.entry_distance_from_local_low_pct = entry_distance_from_local_low_pct
        self.price_change_15m_pct = price_change_15m_pct
        self.price_change_30m_pct = price_change_30m_pct
        self.price_change_60m_pct = price_change_60m_pct
        self.data_quality = data_quality

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "token_mint": self.token_mint,
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price,
            "price_5m_before": self.price_5m_before,
            "price_15m_before": self.price_15m_before,
            "price_30m_before": self.price_30m_before,
            "price_60m_before": self.price_60m_before,
            "local_low_60m": self.local_low_60m,
            "entry_distance_from_local_low_pct": self.entry_distance_from_local_low_pct,
            "price_change_15m_pct": self.price_change_15m_pct,
            "price_change_30m_pct": self.price_change_30m_pct,
            "price_change_60m_pct": self.price_change_60m_pct,
            "data_quality": self.data_quality,
        }


class EntryTimingAnalyzer:
    """Analyze price action around a paper trade entry point."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = PriceSnapshotRepository(session)

    async def compute(
        self,
        token_mint: str,
        entry_time: datetime,
        entry_price: float,
    ) -> EntryTimingMetrics:
        """Compute entry timing metrics for a trade.

        Args:
            token_mint: Token mint address
            entry_time: When the position was opened
            entry_price: Entry price of the position

        Returns:
            EntryTimingMetrics with all computed fields
        """
        # Ensure entry_time is timezone-aware
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)

        # Define lookback window
        window_start = entry_time - timedelta(minutes=60)
        window_end = entry_time

        # Fetch all snapshots in the 60m window
        snapshots = await self._repo.get_range(
            token_mint, window_start, window_end
        )

        # Determine data quality
        data_quality = (
            "sufficient_history"
            if len(snapshots) >= MIN_SNAPSHOTS_FOR_METRICS
            else "insufficient_history"
        )

        # Extract prices at offsets (nearest snapshot before target time)
        price_5m = self._find_nearest_price(snapshots, entry_time, minutes_before=5)
        price_15m = self._find_nearest_price(snapshots, entry_time, minutes_before=15)
        price_30m = self._find_nearest_price(snapshots, entry_time, minutes_before=30)
        price_60m = self._find_nearest_price(snapshots, entry_time, minutes_before=60)

        # Local low in the 60m window
        local_low = None
        if snapshots:
            local_low = min(s.price for s in snapshots)

        # Distance from local low
        distance_from_low = None
        if local_low is not None and local_low > 0 and entry_price is not None:
            distance_from_low = ((entry_price - local_low) / local_low) * 100

        # Price changes
        change_15m = self._compute_change(price_15m, entry_price)
        change_30m = self._compute_change(price_30m, entry_price)
        change_60m = self._compute_change(price_60m, entry_price)

        return EntryTimingMetrics(
            token_mint=token_mint,
            entry_time=entry_time,
            entry_price=entry_price,
            price_5m_before=price_5m,
            price_15m_before=price_15m,
            price_30m_before=price_30m,
            price_60m_before=price_60m,
            local_low_60m=local_low,
            entry_distance_from_local_low_pct=(
                round(distance_from_low, 4) if distance_from_low is not None else None
            ),
            price_change_15m_pct=change_15m,
            price_change_30m_pct=change_30m,
            price_change_60m_pct=change_60m,
            data_quality=data_quality,
        )

    def _find_nearest_price(
        self,
        snapshots: list[TokenPriceSnapshot],
        entry_time: datetime,
        minutes_before: int,
    ) -> float | None:
        """Find price of the snapshot closest to (entry_time - minutes_before).

        Looks for the snapshot within +/- 2 minutes of the target time
        to handle non-uniform snapshot intervals.
        """
        target = entry_time - timedelta(minutes=minutes_before)
        tolerance = timedelta(minutes=2)

        best: TokenPriceSnapshot | None = None
        best_delta: timedelta | None = None

        for snap in snapshots:
            delta = abs(snap.fetched_at - target)
            if delta <= tolerance:
                if best_delta is None or delta < best_delta:
                    best = snap
                    best_delta = delta

        return float(best.price) if best is not None else None

    @staticmethod
    def _compute_change(
        earlier_price: float | None,
        later_price: float | None,
    ) -> float | None:
        """Compute percentage change from earlier to later price."""
        if earlier_price is None or later_price is None:
            return None
        if earlier_price <= 0:
            return None
        return round(((later_price - earlier_price) / earlier_price) * 100, 4)
