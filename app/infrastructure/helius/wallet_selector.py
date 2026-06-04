"""Wallet selector — selects top wallets for Helius webhook monitoring.

Ranks wallets from wallet_metrics by quality signals:
- Recent activity (last_trade_at)
- Win rate
- Realized PnL
- Trade count (engagement)
- Token diversity (early discovery)

Deterministic ordering for reproducibility.
Excludes invalid addresses.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Base58 Solana address pattern (32-44 chars)
_WALLET_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_solana_address(addr: str) -> bool:
    """Check if string looks like a valid Solana address."""
    return bool(_WALLET_RE.match(addr))


class WalletSelector:
    """Select top-N wallets for Helius webhook monitoring."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def select_wallets(
        self,
        max_wallets: int = 3000,
    ) -> list[str]:
        """Select top wallets ranked by quality signals.

        Ranking formula (deterministic):
        - Recent activity: last_trade_at recency
        - Win rate: higher is better
        - Realized PnL: positive PnL preferred
        - Trade count: more trades = more reliable signal
        - Token diversity: more tokens = early discovery

        Returns:
            List of wallet addresses (strings), max `max_wallets`.
        """
        session = self._session_factory()
        try:
            # Composite quality score:
            # - recency_score: days since last trade (lower = better, normalized)
            # - win_rate: 0-1
            # - pnl_score: log-normalized positive PnL
            # - engagement: trade count / 100 (capped at 1.0)
            # - diversity: unique tokens / 50 (capped at 1.0)
            stmt = text("""
                WITH scored AS (
                    SELECT
                        wallet,
                        -- Recency: 0 = today, higher = older, capped at 90 days
                        LEAST(
                            EXTRACT(EPOCH FROM (now() - COALESCE(last_trade_at, first_trade_at, now()))) / 86400,
                            90
                        ) AS days_since_trade,
                        win_rate,
                        total_realized_pnl,
                        total_trades,
                        total_unique_tokens,
                        last_trade_at,
                        -- Composite quality score
                        (
                            -- Recency component (0-1, higher = more recent)
                            GREATEST(0, 1.0 - LEAST(
                                EXTRACT(EPOCH FROM (now() - COALESCE(last_trade_at, first_trade_at, now()))) / 86400,
                                90
                            ) / 90.0) * 0.30
                            +
                            -- Win rate component (0-1)
                            COALESCE(win_rate, 0) * 0.25
                            +
                            -- PnL component (log-normalized, positive = good)
                            CASE
                                WHEN total_realized_pnl > 0 THEN
                                    LEAST(ln(total_realized_pnl + 1) / 15.0, 1.0) * 0.20
                                ELSE 0
                            END
                            +
                            -- Engagement component (trade count / 100, capped)
                            LEAST(total_trades / 100.0, 1.0) * 0.15
                            +
                            -- Diversity component (unique tokens / 50, capped)
                            LEAST(total_unique_tokens / 50.0, 1.0) * 0.10
                        ) AS quality_score
                    FROM wallet_metrics
                    WHERE wallet IS NOT NULL
                      AND length(wallet) >= 32
                      AND total_trades >= 1
                )
                SELECT wallet, quality_score
                FROM scored
                ORDER BY quality_score DESC, wallet ASC
                LIMIT :max_wallets
            """)

            result = await session.execute(
                stmt, {"max_wallets": max_wallets}
            )
            rows = result.fetchall()

            wallets = []
            for row in rows:
                addr = row[0]
                if is_valid_solana_address(addr):
                    wallets.append(addr)

            logger.info(
                "wallet_selector.selected",
                total_candidates=len(rows),
                valid_wallets=len(wallets),
                max_requested=max_wallets,
            )

            return wallets

        except Exception as e:
            logger.error("wallet_selector.error", error=str(e)[:200])
            return []
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
            logger.error("wallet_selector.stats_error", error=str(e)[:200])
            return {}
        finally:
            await session.close()
