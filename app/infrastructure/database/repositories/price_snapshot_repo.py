"""Price snapshot repository — async CRUD for token price snapshots.

Design:
- Batch insert for performance
- Dedup by (token_mint, fetched_at) within a threshold
- Retention cleanup
- Time-range queries for entry timing analysis
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.token_price_snapshot import TokenPriceSnapshot

logger = structlog.get_logger(__name__)


class PriceSnapshotRepository:
    """Async repository for token price snapshot persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_batch(
        self,
        snapshots: list[dict[str, Any]],
        dedup_window_seconds: int = 60,
    ) -> int:
        """Insert a batch of price snapshots with dedup.

        Args:
            snapshots: List of dicts with keys:
                token_mint, price, source, confidence, slot, context,
                fetched_at, metadata_json
            dedup_window_seconds: Skip if snapshot exists within this window

        Returns:
            Number of snapshots inserted
        """
        if not snapshots:
            return 0

        inserted = 0
        for snap in snapshots:
            token_mint = snap["token_mint"]
            fetched_at = snap["fetched_at"]

            # Dedup check: skip if snapshot exists within window
            cutoff = fetched_at - __import__("datetime").timedelta(
                seconds=dedup_window_seconds
            )
            exists_stmt = (
                select(func.count())
                .select_from(TokenPriceSnapshot)
                .where(
                    and_(
                        TokenPriceSnapshot.token_mint == token_mint,
                        TokenPriceSnapshot.fetched_at >= cutoff,
                        TokenPriceSnapshot.fetched_at <= fetched_at,
                    )
                )
            )
            result = await self._session.execute(exists_stmt)
            if (result.scalar() or 0) > 0:
                continue

            record = TokenPriceSnapshot(
                id=uuid.uuid4(),
                token_mint=token_mint,
                price=snap["price"],
                source=snap["source"],
                confidence=snap.get("confidence", 1.0),
                slot=snap.get("slot"),
                context=snap.get("context", "scheduled"),
                metadata_json=snap.get("metadata_json"),
                fetched_at=fetched_at,
            )
            self._session.add(record)
            inserted += 1

        if inserted > 0:
            await self._session.flush()

        return inserted

    async def get_latest(
        self,
        token_mint: str,
        limit: int = 100,
    ) -> list[TokenPriceSnapshot]:
        """Get latest snapshots for a token.

        Returns:
            List of snapshots ordered by fetched_at DESC
        """
        stmt = (
            select(TokenPriceSnapshot)
            .where(TokenPriceSnapshot.token_mint == token_mint)
            .order_by(TokenPriceSnapshot.fetched_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_range(
        self,
        token_mint: str,
        start: datetime,
        end: datetime,
    ) -> list[TokenPriceSnapshot]:
        """Get snapshots for a token within a time range.

        Returns:
            List of snapshots ordered by fetched_at ASC
        """
        stmt = (
            select(TokenPriceSnapshot)
            .where(
                and_(
                    TokenPriceSnapshot.token_mint == token_mint,
                    TokenPriceSnapshot.fetched_at >= start,
                    TokenPriceSnapshot.fetched_at <= end,
                )
            )
            .order_by(TokenPriceSnapshot.fetched_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_nearest_before(
        self,
        token_mint: str,
        target_time: datetime,
    ) -> TokenPriceSnapshot | None:
        """Get the snapshot closest to (but not after) target_time.

        Returns:
            Snapshot or None if no data before target_time
        """
        stmt = (
            select(TokenPriceSnapshot)
            .where(
                and_(
                    TokenPriceSnapshot.token_mint == token_mint,
                    TokenPriceSnapshot.fetched_at <= target_time,
                )
            )
            .order_by(TokenPriceSnapshot.fetched_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_before(self, cutoff: datetime) -> int:
        """Delete snapshots older than cutoff.

        Returns:
            Number of rows deleted
        """
        count_stmt = (
            select(func.count())
            .select_from(TokenPriceSnapshot)
            .where(TokenPriceSnapshot.fetched_at < cutoff)
        )
        count_result = await self._session.execute(count_stmt)
        count = count_result.scalar() or 0

        if count == 0:
            return 0

        delete_stmt = delete(TokenPriceSnapshot).where(
            TokenPriceSnapshot.fetched_at < cutoff
        )
        await self._session.execute(delete_stmt)
        return count

    async def get_distinct_mints(self, limit: int = 500) -> list[str]:
        """Get distinct token mints that have snapshots.

        Returns:
            List of unique token mint addresses
        """
        stmt = (
            select(func.distinct(TokenPriceSnapshot.token_mint))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.fetchall()]
