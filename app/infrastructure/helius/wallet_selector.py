"""Wallet selector v2 — alpha-per-credit scoring for Helius credit saving.

Ranks wallets from wallet_metrics by quality signals, penalizing noisy wallets
that consume credits without contributing alpha.

v2 changes:
- Exclude zero-trade wallets (bots/programs)
- Exclude zero-alpha wallets (win_rate=0 AND PnL<=0)
- Exclude top-N noisy event generators with zero alpha
- Penalize excessive event volume relative to alpha contribution
- Audit method for before/after comparison

Deterministic ordering for reproducibility.
Excludes invalid addresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings

logger = structlog.get_logger(__name__)

# Base58 Solana address pattern (32-44 chars)
_WALLET_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_solana_address(addr: str) -> bool:
    """Check if string looks like a valid Solana address."""
    return bool(_WALLET_RE.match(addr))


def mask_wallet(addr: str) -> str:
    """Mask wallet address for safe logging."""
    if len(addr) <= 10:
        return addr
    return addr[:6] + "..." + addr[-4:]


@dataclass
class SelectionAudit:
    """Audit result for wallet selection."""

    total_wallets_in_pool: int = 0
    selected_wallet_count: int = 0
    excluded_zero_trade_count: int = 0
    excluded_zero_alpha_count: int = 0
    excluded_noisy_count: int = 0
    excluded_low_score_count: int = 0
    estimated_events_per_hour_before: int = 0
    estimated_events_per_hour_after: int = 0
    estimated_credit_savings_pct: float = 0.0
    top_excluded_wallets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_wallets_in_pool": self.total_wallets_in_pool,
            "selected_wallet_count": self.selected_wallet_count,
            "excluded_zero_trade_count": self.excluded_zero_trade_count,
            "excluded_zero_alpha_count": self.excluded_zero_alpha_count,
            "excluded_noisy_count": self.excluded_noisy_count,
            "excluded_low_score_count": self.excluded_low_score_count,
            "estimated_events_per_hour_before": self.estimated_events_per_hour_before,
            "estimated_events_per_hour_after": self.estimated_events_per_hour_after,
            "estimated_credit_savings_pct": round(self.estimated_credit_savings_pct, 1),
            "top_excluded_wallets": self.top_excluded_wallets[:20],
        }


class WalletSelector:
    """Select top-N wallets for Helius webhook monitoring using alpha-per-credit scoring."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def select_wallets(
        self,
        max_wallets: int | None = None,
    ) -> list[str]:
        """Select top wallets ranked by alpha-per-credit score.

        Scoring:
        - alpha_score = quality components (win_rate, PnL, recency, engagement, diversity)
        - noise_penalty = excessive events/trades with low alpha
        - final_score = alpha_score * (1 - noise_penalty)

        Exclusions (applied before scoring):
        - total_trades = 0 (bots/programs)
        - win_rate = 0 AND total_realized_pnl <= 0 (zero-alpha)
        - top-N noisy event generators with zero alpha (from raw_events)
        - final_score < HELIUS_MIN_ALPHA_SCORE

        Returns:
            List of wallet addresses (strings), max `max_wallets`.
        """
        if max_wallets is None:
            max_wallets = settings.HELIUS_MAX_MONITORED_WALLETS

        session = self._session_factory()
        try:
            # Step 1: Get noisy wallets from raw_events
            noisy_set = set()
            try:
                noisy_list = await self._get_noisy_wallets(session)
                noisy_set = set(noisy_list)
                if noisy_set:
                    logger.info(
                        "wallet_selector_v2.noisy_wallets",
                        count=len(noisy_set),
                    )
            except Exception as e:
                logger.warning("wallet_selector_v2.noisy_query_failed", error=str(e)[:100])

            # Step 2: Get all candidate wallets with metrics
            stmt = text("""
                SELECT
                    wallet,
                    total_trades,
                    win_rate,
                    total_realized_pnl,
                    total_unique_tokens,
                    last_trade_at,
                    first_trade_at
                FROM wallet_metrics
                WHERE wallet IS NOT NULL
                  AND length(wallet) >= 32
                ORDER BY wallet
            """)

            result = await session.execute(stmt)
            rows = result.fetchall()

            # Step 3: Score and filter in Python
            candidates = []
            excluded_zero_trade = 0
            excluded_zero_alpha = 0
            excluded_noisy = 0
            excluded_low_score = 0

            for row in rows:
                wallet = row[0]
                trades = row[1] or 0
                win_rate = float(row[2] or 0)
                pnl = float(row[3] or 0)
                tokens = row[4] or 0
                last_trade = row[5]
                first_trade = row[6]

                # Exclusion: zero-trade wallets (bots/programs)
                if settings.HELIUS_EXCLUDE_ZERO_TRADE_WALLETS and trades < 1:
                    excluded_zero_trade += 1
                    continue

                # Exclusion: zero-alpha wallets
                if settings.HELIUS_EXCLUDE_ZERO_ALPHA_WALLETS and win_rate <= 0 and pnl <= 0:
                    excluded_zero_alpha += 1
                    continue

                # Compute alpha score
                alpha_score = self._compute_alpha_score(
                    win_rate=win_rate,
                    pnl=pnl,
                    trades=trades,
                    tokens=tokens,
                    last_trade=last_trade,
                    first_trade=first_trade,
                )

                # Noise penalty
                noise_penalty = 0.0
                if trades > 500 and win_rate < 0.1:
                    noise_penalty = min(trades / 1000.0, 0.8)
                elif tokens > 100 and pnl <= 0:
                    noise_penalty = min(tokens / 200.0, 0.5)

                # Noisy wallet penalty
                is_noisy = wallet in noisy_set
                noisy_multiplier = 0.1 if is_noisy else 1.0
                if is_noisy:
                    excluded_noisy += 1

                # Final score
                final_score = alpha_score * (1.0 - noise_penalty) * noisy_multiplier

                # Exclusion: minimum alpha score
                if final_score < settings.HELIUS_MIN_ALPHA_SCORE:
                    excluded_low_score += 1
                    continue

                if is_valid_solana_address(wallet):
                    candidates.append((wallet, final_score))

            # Step 4: Sort by score descending, take top N
            candidates.sort(key=lambda x: (-x[1], x[0]))
            wallets = [w for w, _ in candidates[:max_wallets]]

            logger.info(
                "wallet_selector_v2.selected",
                total_pool=len(rows),
                selected=len(wallets),
                excluded_zero_trade=excluded_zero_trade,
                excluded_zero_alpha=excluded_zero_alpha,
                excluded_noisy=excluded_noisy,
                excluded_low_score=excluded_low_score,
                max_requested=max_wallets,
            )

            return wallets

        except Exception as e:
            logger.error("wallet_selector_v2.error", error=str(e)[:200])
            return []
        finally:
            await session.close()

    def _compute_alpha_score(
        self,
        win_rate: float,
        pnl: float,
        trades: int,
        tokens: int,
        last_trade: Any,
        first_trade: Any,
    ) -> float:
        """Compute alpha quality score for a wallet."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        # Recency (0-1, higher = more recent)
        ref_time = last_trade or first_trade
        if ref_time:
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            days_since = (now - ref_time).total_seconds() / 86400
            recency = max(0, 1.0 - min(days_since, 90) / 90.0)
        else:
            recency = 0.0

        # Win rate (0-1)
        wr = max(0, min(win_rate, 1.0))

        # PnL (log-normalized, positive = good)
        if pnl > 0:
            import math
            pnl_score = min(math.log(pnl + 1) / 15.0, 1.0)
        else:
            pnl_score = 0.0

        # Engagement (trade count / 100, capped)
        engagement = min(trades / 100.0, 1.0)

        # Diversity (unique tokens / 50, capped)
        diversity = min(tokens / 50.0, 1.0)

        # Weighted composite
        score = (
            recency * 0.30
            + wr * 0.25
            + pnl_score * 0.20
            + engagement * 0.15
            + diversity * 0.10
        )

        return score

    async def _get_noisy_wallets(self, session: AsyncSession) -> list[str]:
        """Get top-N noisy event generators from raw_events."""
        lookback = settings.HELIUS_NOISY_WALLET_LOOKBACK_HOURS
        exclude_n = settings.HELIUS_NOISY_WALLET_EXCLUDE_TOP_N
        min_events = settings.HELIUS_MAX_EVENTS_PER_WALLET_HOUR

        stmt = text("""
            SELECT wallet
            FROM (
                SELECT
                    payload->'account_data'->0->>'account' AS wallet,
                    count(*) AS cnt
                FROM raw_events
                WHERE created_at >= now() - (:lookback || ' hours')::interval
                  AND payload->'account_data'->0->>'account' IS NOT NULL
                  AND payload->'account_data'->0->>'account' != ''
                GROUP BY 1
                HAVING count(*) >= :min_events
                ORDER BY cnt DESC
                LIMIT :exclude_n
            ) sub
        """)

        result = await session.execute(
            stmt,
            {
                "lookback": lookback,
                "exclude_n": exclude_n,
                "min_events": min_events,
            },
        )
        return [row[0] for row in result.fetchall() if row[0]]

    async def audit_selection(self) -> SelectionAudit:
        """Run selection audit: compare before/after wallet counts and event rates."""
        audit = SelectionAudit()
        session = self._session_factory()
        try:
            # Total wallets in pool
            r = await session.execute(
                text("SELECT count(*) FROM wallet_metrics WHERE wallet IS NOT NULL AND length(wallet) >= 32")
            )
            audit.total_wallets_in_pool = r.scalar() or 0

            # Count exclusions by type
            r = await session.execute(text("""
                SELECT
                    count(*) FILTER (WHERE total_trades = 0) AS zero_trade,
                    count(*) FILTER (WHERE total_trades > 0 AND win_rate = 0 AND total_realized_pnl <= 0) AS zero_alpha
                FROM wallet_metrics
                WHERE wallet IS NOT NULL AND length(wallet) >= 32
            """))
            row = r.fetchone()
            if row:
                audit.excluded_zero_trade_count = row[0]
                audit.excluded_zero_alpha_count = row[1]

            # Noisy wallets
            try:
                noisy_wallets = await self._get_noisy_wallets(session)
                audit.excluded_noisy_count = len(noisy_wallets)
            except Exception:
                pass

            # Selected wallets
            selected = await self.select_wallets()
            audit.selected_wallet_count = len(selected)

            # Low score exclusions
            audit.excluded_low_score_count = max(
                0,
                audit.total_wallets_in_pool
                - audit.excluded_zero_trade_count
                - audit.excluded_zero_alpha_count
                - audit.excluded_noisy_count
                - audit.selected_wallet_count,
            )

            # Estimate events before/after
            r = await session.execute(text("""
                SELECT count(*) FROM raw_events
                WHERE created_at >= now() - interval '1 hour'
                  AND payload->'account_data'->0->>'account' IS NOT NULL
            """))
            total_events = r.scalar() or 0
            audit.estimated_events_per_hour_before = total_events

            if selected:
                # Sample selected wallets for event count estimate
                sample = selected[:500]
                r2 = await session.execute(
                    text("""
                        SELECT count(*) FROM raw_events
                        WHERE created_at >= now() - interval '1 hour'
                          AND payload->'account_data'->0->>'account' = ANY(:wallets)
                    """),
                    {"wallets": sample},
                )
                sample_events = r2.scalar() or 0
                if len(selected) <= 500:
                    audit.estimated_events_per_hour_after = sample_events
                else:
                    audit.estimated_events_per_hour_after = int(
                        sample_events * len(selected) / min(len(selected), 500)
                    )

            if audit.estimated_events_per_hour_before > 0:
                savings = 1.0 - (
                    audit.estimated_events_per_hour_after
                    / audit.estimated_events_per_hour_before
                )
                audit.estimated_credit_savings_pct = savings * 100

            # Top event-generating wallets (masked)
            r = await session.execute(text("""
                SELECT payload->'account_data'->0->>'account' AS wallet
                FROM raw_events
                WHERE created_at >= now() - interval '1 hour'
                  AND payload->'account_data'->0->>'account' IS NOT NULL
                  AND payload->'account_data'->0->>'account' != ''
                GROUP BY 1
                ORDER BY count(*) DESC
                LIMIT 20
            """))
            audit.top_excluded_wallets = [
                mask_wallet(row[0]) for row in r.fetchall() if row[0]
            ]

            logger.info("wallet_selector_v2.audit", **audit.to_dict())
            return audit

        except Exception as e:
            logger.error("wallet_selector_v2.audit_error", error=str(e)[:200])
            return audit
        finally:
            await session.close()

    async def get_wallet_stats(self) -> dict[str, Any]:
        """Get summary stats about wallet pool."""
        session = self._session_factory()
        try:
            stmt = text("""
                SELECT
                    count(*) AS total_wallets,
                    count(*) FILTER (WHERE total_trades >= 1) AS active_wallets,
                    count(*) FILTER (WHERE last_trade_at >= now() - interval '7 days') AS active_7d,
                    count(*) FILTER (WHERE last_trade_at >= now() - interval '30 days') AS active_30d,
                    avg(win_rate) AS avg_win_rate,
                    avg(total_trades) AS avg_trades,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY total_realized_pnl) AS median_pnl
                FROM wallet_metrics
            """)
            result = await session.execute(stmt)
            row = result.fetchone()
            if not row:
                return {}
            return {
                "total_wallets": row[0],
                "active_wallets": row[1],
                "active_7d": row[2],
                "active_30d": row[3],
                "avg_win_rate": round(float(row[4] or 0), 4),
                "avg_trades": round(float(row[5] or 0), 1),
                "median_pnl": round(float(row[6] or 0), 4),
            }
        except Exception as e:
            logger.error("wallet_selector_v2.stats_error", error=str(e)[:200])
            return {}
        finally:
            await session.close()
