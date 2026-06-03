"""Price snapshot service — orchestrates price snapshot capture and retention.

Responsibilities:
- Capture snapshots from PricingService into DB
- Manage retention (delete old snapshots)
- Dedup/throttle to avoid redundant writes
- Coordinate snapshot contexts (paper, ranked, scheduled)

Safety:
- Never raises on write failures (logs and continues)
- Skips tokens with unavailable prices
- Deduplicates by (token_mint, fetched_at) window
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.pricing_service import PricingService
from app.config.settings import settings
from app.infrastructure.database.repositories.price_snapshot_repo import (
    PriceSnapshotRepository,
)
from app.schemas.pricing import TokenPrice

logger = structlog.get_logger(__name__)


class PriceSnapshotService:
    """Orchestrates price snapshot persistence and lifecycle."""

    def __init__(
        self,
        pricing_service: PricingService,
    ) -> None:
        self._pricing = pricing_service

    async def capture_snapshots(
        self,
        session: AsyncSession,
        token_mints: list[str],
        context: str = "scheduled",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Fetch prices and persist as snapshots.

        Args:
            session: Async database session
            token_mints: Tokens to snapshot
            context: One of "paper_candidate", "paper_position", "ranked_token", "scheduled"
            metadata: Optional metadata to attach to each snapshot

        Returns:
            Number of snapshots inserted (after dedup)
        """
        if not token_mints:
            return 0

        # Deduplicate mints
        unique_mints = list(set(token_mints))

        # Fetch prices — failures are non-fatal
        try:
            prices = await self._pricing.get_batch_prices(
                unique_mints, force_refresh=True
            )
        except Exception as e:
            logger.error(
                "price_snapshot.fetch_error",
                context=context,
                error=str(e)[:200],
            )
            return 0

        if not prices:
            logger.warning(
                "price_snapshot.no_prices",
                context=context,
                requested=len(unique_mints),
            )
            return 0

        # Build snapshot dicts
        now = datetime.now(timezone.utc)
        snapshots: list[dict[str, Any]] = []
        for mint, price_obj in prices.items():
            if price_obj is None:
                continue
            snapshots.append(
                {
                    "token_mint": mint,
                    "price": float(price_obj.price),
                    "source": price_obj.source,
                    "confidence": float(price_obj.confidence),
                    "slot": None,  # Jupiter doesn't provide slot
                    "context": context,
                    "fetched_at": now,
                    "metadata_json": metadata,
                }
            )

        if not snapshots:
            return 0

        # Insert with dedup
        try:
            repo = PriceSnapshotRepository(session)
            inserted = await repo.insert_batch(
                snapshots,
                dedup_window_seconds=settings.PRICE_SNAPSHOT_DEDUP_WINDOW_SECONDS,
            )
            logger.info(
                "price_snapshot.captured",
                context=context,
                requested=len(unique_mints),
                fetched=len(prices),
                inserted=inserted,
            )
            return inserted
        except Exception as e:
            logger.error(
                "price_snapshot.insert_error",
                context=context,
                error=str(e)[:200],
            )
            return 0

    async def capture_for_paper_candidate(
        self,
        session: AsyncSession,
        token_mint: str,
        candidate_metadata: dict[str, Any] | None = None,
    ) -> int:
        """Capture snapshot for a paper trading candidate.

        Called when a candidate passes initial filters but before
        position creation.
        """
        return await self.capture_snapshots(
            session,
            [token_mint],
            context="paper_candidate",
            metadata=candidate_metadata,
        )

    async def capture_for_open_positions(
        self,
        session: AsyncSession,
        token_mints: list[str],
    ) -> int:
        """Capture snapshots for all tokens with open paper positions.

        Called periodically by PaperTradingWorker lifecycle cycle.
        """
        return await self.capture_snapshots(
            session,
            token_mints,
            context="paper_position",
        )

    async def capture_for_ranked_tokens(
        self,
        session: AsyncSession,
        ranked_tokens: list[dict[str, Any]],
    ) -> int:
        """Capture snapshots for top-ranked tokens.

        Args:
            ranked_tokens: List of dicts with at least 'token_mint' key

        Called after batch rank computation by RankingWorker.
        Deduplicates mints and limits to PRICE_SNAPSHOT_TOP_RANKED_LIMIT.
        """
        if not ranked_tokens:
            return 0

        # Deduplicate by token_mint, preserving order
        seen: set[str] = set()
        unique_tokens: list[dict[str, Any]] = []
        for tok in ranked_tokens:
            mint = tok.get("token_mint") or tok.get("token", "")
            if mint and mint not in seen:
                seen.add(mint)
                unique_tokens.append(tok)

        # Limit to top N
        limit = settings.PRICE_SNAPSHOT_TOP_RANKED_LIMIT
        limited = unique_tokens[:limit]

        mints = [t.get("token_mint") or t.get("token", "") for t in limited]
        mints = [m for m in mints if m]

        return await self.capture_snapshots(
            session,
            mints,
            context="ranked_token",
        )

    async def run_retention(self, session: AsyncSession) -> int:
        """Delete snapshots older than retention period.

        Returns:
            Number of rows deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=settings.PRICE_SNAPSHOT_RETENTION_DAYS
        )
        try:
            repo = PriceSnapshotRepository(session)
            deleted = await repo.delete_before(cutoff)
            if deleted > 0:
                logger.info(
                    "price_snapshot.retention",
                    deleted=deleted,
                    cutoff=cutoff.isoformat(),
                )
            return deleted
        except Exception as e:
            logger.error("price_snapshot.retention_error", error=str(e)[:200])
            return 0
