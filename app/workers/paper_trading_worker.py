"""Paper trading worker — manages virtual positions from ranked candidates.

Pipeline position: RANKINGS → paper_trading

This worker:
1. Receives ranked candidates from RankingWorker via PAPER_TRADING stream
2. Evaluates candidates against entry rules
3. In dry-run mode: records candidates as SKIPPED (visibility only)
4. In live mode: fetches entry price via PricingService, creates OPEN position
5. Monitors OPEN positions for TP/SL/timeout exit conditions
6. Persists positions, outcomes, and snapshots to DB

Safety guarantees:
- PAPER_TRADING_ENABLED=false: no positions created at all
- PAPER_TRADING_DRY_RUN=true: candidates logged as SKIPPED, never OPEN
- Never executes real trades or signs transactions
- Never uses wallet private keys
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, text

from app.config.settings import settings
from app.infrastructure.database.models.paper_trading import (
    PaperPortfolioSnapshot,
    PaperPosition,
    PaperTradeOutcome,
)
from app.infrastructure.database.models.wallet_position import WalletPosition

logger = structlog.get_logger(__name__)

# Exit thresholds
TAKE_PROFIT_1_PCT = 20.0
TAKE_PROFIT_2_PCT = 50.0
STOP_LOSS_PCT = -10.0
TIMEOUT_HOURS = 24


class PaperTradingWorker:
    """Manages virtual paper trading positions from ranked candidates."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory
        self._pricing: Any = None
        self._running = False
        self._last_snapshot: datetime | None = None
        self._cycle_count = 0
        # Price feed stats
        self._price_success_count = 0
        self._price_failure_count = 0
        self._price_unavailable_tokens: list[str] = []
        # Price snapshot integration
        self._snapshot_service: Any = None
        self._last_price_snapshot: datetime | None = None
        self._last_retention_run: datetime | None = None

    async def run(self) -> None:
        """Main loop: process candidates, monitor positions, take snapshots."""
        self._running = True
        logger.info(
            "paper_worker.starting",
            enabled=settings.PAPER_TRADING_ENABLED,
            dry_run=settings.PAPER_TRADING_DRY_RUN,
        )

        # Lazily initialize pricing service
        await self._init_pricing()

        while self._running:
            try:
                await self._lifecycle_cycle()
                self._cycle_count += 1
            except Exception as e:
                logger.error("paper_worker.cycle_error", error=str(e))
            await asyncio.sleep(60)

        logger.info("paper_worker.stopped")

    async def shutdown(self) -> None:
        """Signal shutdown."""
        self._running = False

    async def _init_pricing(self) -> None:
        """Initialize PricingService (Jupiter + Redis cache) and PriceSnapshotService."""
        try:
            from redis.asyncio import Redis

            from app.analytics.pricing_service import PricingService
            from app.infrastructure.external.jupiter_client import (
                JupiterPriceClient,
            )
            from app.infrastructure.redis.price_cache import TokenPriceCache

            redis = Redis.from_url(settings.REDIS_CACHE_URL, decode_responses=True)
            jupiter = JupiterPriceClient()
            cache = TokenPriceCache(redis)
            self._pricing = PricingService(jupiter, cache)
            logger.info("paper_worker.pricing_initialized")

            # Initialize price snapshot service if enabled
            if settings.PRICE_SNAPSHOT_ENABLED:
                from app.analytics.price_snapshot_service import PriceSnapshotService
                self._snapshot_service = PriceSnapshotService(self._pricing)
                logger.info("paper_worker.snapshot_service_initialized")
        except Exception as e:
            logger.warning("paper_worker.pricing_init_failed", error=str(e))
            self._pricing = None

    async def _lifecycle_cycle(self) -> None:
        """Run one lifecycle cycle."""
        now = datetime.now(timezone.utc)

        # 1. Monitor OPEN positions (price refresh + exit check)
        await self._monitor_positions()

        # 2. Periodic portfolio snapshot
        if self._should_snapshot(now):
            await self._take_snapshot(now)
            self._last_snapshot = now

        # 3. Price snapshot for open positions (non-fatal)
        if self._snapshot_service and self._should_price_snapshot(now):
            await self._capture_open_position_snapshots()
            self._last_price_snapshot = now

        # 4. Retention cleanup (hourly)
        if self._should_run_retention(now):
            await self._run_snapshot_retention()
            self._last_retention_run = now

        logger.debug("paper_worker.cycle_done", cycle=self._cycle_count)

    # ── Candidate Processing ────────────────────────────────

    async def process_candidate(self, candidate: dict[str, Any]) -> None:
        """Process a single paper trading candidate.

        Called by the stream consumer or directly by RankingWorker.
        """
        token = candidate.get("token", "")
        score = candidate.get("score", 0)
        rank = candidate.get("rank", 0)

        if not token:
            return

        # Guard: dry-run mode — record SKIPPED, never create OPEN position
        # Still runs entry timing analysis for audit visibility
        if not settings.PAPER_TRADING_ENABLED or settings.PAPER_TRADING_DRY_RUN:
            entry_price = await self._fetch_price(token)
            timing_result: dict[str, Any] = {"passed": True, "skip_reason": "", "metrics": None, "warnings": []}
            if entry_price and entry_price > 0:
                timing_result = await self._check_entry_timing(token, entry_price)
            skip_reason = timing_result["skip_reason"] if not timing_result["passed"] else "dry_run_mode"
            timing_data = {"entry_timing": timing_result["metrics"], "warnings": timing_result["warnings"]} if timing_result["metrics"] else None
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason=skip_reason,
                candidate=candidate,
                activity_data=timing_data,
            )
            logger.info(
                "paper.candidate_dry_run",
                token=token[:16],
                score=score,
                rank=rank,
                skip_reason=skip_reason,
            )
            return

        # Guard: max open positions
        open_count = await self._count_open_positions()
        if open_count >= settings.PAPER_MAX_POSITIONS:
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason="max_positions_reached",
                candidate=candidate,
            )
            return

        # Guard: already have open position for this token
        if await self._has_open_position(token):
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason="duplicate_token",
                candidate=candidate,
            )
            return

        # Guard: token activity filter
        activity = await self._check_token_activity(token)
        if not activity["passed"]:
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason=activity["skip_reason"],
                candidate=candidate,
                activity_data=activity,
            )
            return

        # Guard: parabolic entry confirmation (momentum filter)
        regime = candidate.get("regime", "NORMAL")
        stage = candidate.get("stage", "")
        signals = candidate.get("signals", {})
        # Use token_momentum (activity-based, continuous) if available,
        # fall back to legacy momentum (win_rate-based, binary)
        momentum = 0.0
        if isinstance(signals, dict):
            momentum = signals.get("token_momentum", 0) or 0
            if momentum == 0:
                momentum = signals.get("momentum", 0) or 0
        smart_money = signals.get("smart_money", 0) if isinstance(signals, dict) else 0

        if regime == "PARABOLIC" or stage == "HIGH_PUMP_RISK":
            if momentum < settings.PAPER_PARABOLIC_MIN_MOMENTUM:
                await self._persist_skipped(
                    token=token,
                    score=score,
                    rank=rank,
                    reason="parabolic_no_momentum_confirmation",
                    candidate=candidate,
                    activity_data={"momentum": momentum, "threshold": settings.PAPER_PARABOLIC_MIN_MOMENTUM},
                )
                return

            # Guard: parabolic smart money confirmation
            if smart_money < settings.PAPER_PARABOLIC_MIN_SMART_MONEY:
                await self._persist_skipped(
                    token=token,
                    score=score,
                    rank=rank,
                    reason="parabolic_no_smart_money_confirmation",
                    candidate=candidate,
                    activity_data={"smart_money": smart_money, "threshold": settings.PAPER_PARABOLIC_MIN_SMART_MONEY},
                )
                return

        # Guard: whale concentration filter
        concentration = await self._check_whale_concentration(token)
        if concentration is not None and concentration >= settings.PAPER_MAX_TOP_WALLET_CONCENTRATION:
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason="whale_concentration_risk",
                candidate=candidate,
                activity_data={"top_wallet_concentration": round(concentration, 4)},
            )
            return

        # Fetch entry price
        entry_price = await self._fetch_price(token)
        if entry_price is None or entry_price <= 0:
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason="price_unavailable",
                candidate=candidate,
            )
            return

        # Guard: entry timing analysis (late entry / chasing pump detection)
        timing_result = await self._check_entry_timing(token, entry_price)
        if not timing_result["passed"]:
            await self._persist_skipped(
                token=token,
                score=score,
                rank=rank,
                reason=timing_result["skip_reason"],
                candidate=candidate,
                activity_data={"entry_timing": timing_result["metrics"], "warnings": timing_result["warnings"]},
            )
            return

        # Capture price snapshot for candidate (non-fatal, best-effort)
        await self._capture_candidate_snapshot(token, candidate)

        # Create OPEN position in DB
        await self._persist_open_position(
            token=token,
            score=score,
            rank=rank,
            entry_price=entry_price,
            candidate=candidate,
            entry_timing=timing_result["metrics"],
        )

    # ── Position Monitoring ─────────────────────────────────

    async def _monitor_positions(self) -> None:
        """Refresh prices and check exit conditions for all OPEN positions."""
        if not self._session_factory:
            return

        session = self._session_factory()
        try:
            stmt = select(PaperPosition).where(PaperPosition.status == "OPEN")
            result = await session.execute(stmt)
            positions = result.scalars().all()

            if not positions:
                return

            for pos in positions:
                await self._check_position_exit(session, pos)

            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("paper_worker.monitor_error", error=str(e))
        finally:
            await session.close()

    async def _check_position_exit(
        self, session: Any, pos: PaperPosition
    ) -> None:
        """Check if a position should be closed based on exit rules.

        Also updates position metadata with current_price, current_roi,
        max_return, and max_drawdown for observability.
        """
        current_price = await self._fetch_price(pos.token_mint)
        if current_price is None or current_price <= 0:
            return

        if not pos.entry_price or pos.entry_price <= 0:
            return

        roi_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
        now = datetime.now(timezone.utc)

        # Update position metadata with live metrics
        meta = dict(pos.metadata_json or {})
        meta["current_price"] = round(current_price, 10)
        meta["current_roi"] = round(roi_pct, 4)

        prev_max_return = meta.get("max_return", 0.0)
        prev_max_drawdown = meta.get("max_drawdown", 0.0)
        meta["max_return"] = round(max(prev_max_return, roi_pct), 4)
        meta["max_drawdown"] = round(min(prev_max_drawdown, roi_pct), 4)
        meta["last_price_update"] = now.isoformat()
        pos.metadata_json = meta

        # Determine exit reason
        exit_reason: str | None = None

        # Trailing stop check (highest priority after TP)
        if settings.PAPER_TRAILING_STOP_ENABLED:
            max_ret = meta.get("max_return", 0.0)
            if max_ret >= settings.PAPER_TRAILING_STOP_ACTIVATION_ROI:
                trailing_level = max_ret - settings.PAPER_TRAILING_STOP_DROP_ROI
                meta["trailing_stop_active"] = True
                meta["trailing_stop_level"] = round(trailing_level, 4)
                if roi_pct <= trailing_level:
                    exit_reason = "TRAILING_STOP"

        if exit_reason is None:
            if roi_pct >= TAKE_PROFIT_2_PCT:
                exit_reason = "TAKE_PROFIT_2"
            elif roi_pct >= TAKE_PROFIT_1_PCT:
                exit_reason = "TAKE_PROFIT_1"
            elif roi_pct <= STOP_LOSS_PCT:
                exit_reason = "STOP_LOSS"
            elif pos.opened_at:
                hours_open = (now - pos.opened_at).total_seconds() / 3600

                # Parabolic max hold (shorter than normal timeout)
                pos_regime = meta.get("regime", "NORMAL")
                pos_stage = meta.get("stage", "")
                if pos_regime == "PARABOLIC" or pos_stage == "HIGH_PUMP_RISK":
                    if hours_open >= settings.PAPER_PARABOLIC_MAX_HOLD_HOURS:
                        exit_reason = "PARABOLIC_TIMEOUT"
                elif hours_open >= TIMEOUT_HOURS:
                    exit_reason = "TIMEOUT"

        if exit_reason:
            await self._close_position(session, pos, current_price, roi_pct, exit_reason, now)
        else:
            logger.info(
                "paper.position_updated",
                token=pos.token_mint[:16],
                current_price=round(current_price, 10),
                roi_pct=round(roi_pct, 4),
                max_return=meta["max_return"],
                max_drawdown=meta["max_drawdown"],
            )

    async def _close_position(
        self,
        session: Any,
        pos: PaperPosition,
        exit_price: float,
        roi_pct: float,
        exit_reason: str,
        now: datetime,
        outcome_status: str | None = None,
    ) -> None:
        """Close a position and record the outcome."""
        virtual_size = pos.virtual_size_usd or settings.PAPER_POSITION_SIZE_USD
        pnl_usd = virtual_size * (roi_pct / 100)

        # Update position
        pos.status = "CLOSED"
        pos.exit_reason = exit_reason
        pos.closed_at = now
        pos.metadata_json = {
            **(pos.metadata_json or {}),
            "exit_price": exit_price,
            "roi_pct": round(roi_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
        }

        # Determine outcome status (use override if provided)
        if outcome_status is None:
            if roi_pct > 0:
                outcome_status = "WIN"
            elif roi_pct < 0:
                outcome_status = "LOSS"
            else:
                outcome_status = "BREAKEVEN"

        # Record outcome
        outcome = PaperTradeOutcome(
            id=uuid.uuid4(),
            position_id=pos.id,
            token_mint=pos.token_mint,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            roi=round(roi_pct, 4),
            pnl_usd=round(pnl_usd, 4),
            max_drawdown=round(min(0, roi_pct), 4),
            max_return=round(max(0, roi_pct), 4),
            holding_seconds=int(
                (now - pos.opened_at).total_seconds() if pos.opened_at else 0
            ),
            outcome_status=outcome_status,
            created_at=now,
        )
        session.add(outcome)

        logger.info(
            "paper.position_closed",
            token=pos.token_mint[:16],
            roi_pct=round(roi_pct, 4),
            pnl_usd=round(pnl_usd, 4),
            exit_reason=exit_reason,
            outcome=outcome_status,
        )

    async def close_position_by_token(
        self,
        token_mint: str,
        exit_reason: str,
        outcome_status: str = "INVALID_CANDIDATE",
    ) -> bool:
        """Close an OPEN position for a specific token with custom reason.

        Used for administrative closes (e.g., STALE_ACTIVITY).
        Returns True if position was closed, False if not found.
        """
        if not self._session_factory:
            return False

        session = self._session_factory()
        try:
            stmt = select(PaperPosition).where(
                PaperPosition.token_mint == token_mint,
                PaperPosition.status == "OPEN",
            )
            result = await session.execute(stmt)
            pos = result.scalar_one_or_none()

            if pos is None:
                logger.warning("paper.close_not_found", token=token_mint[:16])
                return False

            # Use current price if available, else entry price
            exit_price = await self._fetch_price(token_mint)
            if exit_price is None or exit_price <= 0:
                meta = pos.metadata_json or {}
                exit_price = meta.get("current_price", pos.entry_price or 0)

            if not pos.entry_price or pos.entry_price <= 0:
                roi_pct = 0.0
            else:
                roi_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100

            now = datetime.now(timezone.utc)
            await self._close_position(session, pos, exit_price, roi_pct, exit_reason, now, outcome_status)
            await session.commit()

            logger.info(
                "paper.position_closed_manual",
                token=token_mint[:16],
                exit_reason=exit_reason,
                outcome_status=outcome_status,
                roi_pct=round(roi_pct, 4),
            )
            return True

        except Exception as e:
            await session.rollback()
            logger.error("paper.close_manual_error", token=token_mint[:16], error=str(e))
            return False
        finally:
            await session.close()

    # ── Token Activity Check ────────────────────────────────

    async def _check_token_activity(self, token: str) -> dict[str, Any]:
        """Check if a token has recent trading activity.

        Returns dict with:
        - passed: bool
        - skip_reason: str (empty if passed)
        - last_activity_age_minutes: float
        - events_15m: int
        - unique_wallets_15m: int
        """
        if not self._session_factory:
            return {"passed": False, "skip_reason": "no_session", "last_activity_age_minutes": -1, "events_15m": 0, "unique_wallets_15m": 0}

        session = self._session_factory()
        try:
            now = datetime.now(timezone.utc)
            cutoff_15m = now - timedelta(minutes=15)
            max_age = timedelta(minutes=settings.PAPER_MAX_TOKEN_ACTIVITY_AGE_MINUTES)

            # 1. Last activity age from wallet_positions
            last_activity_stmt = (
                select(func.max(WalletPosition.last_trade_at))
                .where(WalletPosition.token_mint == token)
            )
            last_activity_result = await session.execute(last_activity_stmt)
            last_activity = last_activity_result.scalar()

            if last_activity is None:
                return {"passed": False, "skip_reason": "stale_token_activity", "last_activity_age_minutes": -1, "events_15m": 0, "unique_wallets_15m": 0}

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            age = now - last_activity
            age_minutes = age.total_seconds() / 60

            if age > max_age:
                return {
                    "passed": False,
                    "skip_reason": "stale_token_activity",
                    "last_activity_age_minutes": round(age_minutes, 1),
                    "events_15m": 0,
                    "unique_wallets_15m": 0,
                }

            # 2. Unique wallets trading this token in last 15m
            wallets_stmt = (
                select(func.count(func.distinct(WalletPosition.wallet)))
                .where(
                    WalletPosition.token_mint == token,
                    WalletPosition.last_trade_at >= cutoff_15m,
                )
            )
            wallets_result = await session.execute(wallets_stmt)
            unique_wallets = wallets_result.scalar() or 0

            # 3. Events mentioning this token in last 15m (from raw_events payload)
            events_stmt = text("""
                SELECT COUNT(*) FROM raw_events
                WHERE created_at >= :cutoff
                AND (
                    payload::text LIKE :token_pattern
                    OR metadata::text LIKE :token_pattern
                )
            """)
            events_result = await session.execute(events_stmt, {
                "cutoff": cutoff_15m,
                "token_pattern": f"%{token}%",
            })
            events_15m = events_result.scalar() or 0

            # 4. Check thresholds
            if events_15m < settings.PAPER_MIN_TOKEN_EVENTS_15M:
                return {
                    "passed": False,
                    "skip_reason": "insufficient_token_activity",
                    "last_activity_age_minutes": round(age_minutes, 1),
                    "events_15m": events_15m,
                    "unique_wallets_15m": unique_wallets,
                }

            if unique_wallets < settings.PAPER_MIN_UNIQUE_WALLETS_15M:
                return {
                    "passed": False,
                    "skip_reason": "insufficient_token_activity",
                    "last_activity_age_minutes": round(age_minutes, 1),
                    "events_15m": events_15m,
                    "unique_wallets_15m": unique_wallets,
                }

            return {
                "passed": True,
                "skip_reason": "",
                "last_activity_age_minutes": round(age_minutes, 1),
                "events_15m": events_15m,
                "unique_wallets_15m": unique_wallets,
            }

        except Exception as e:
            logger.warning("paper.activity_check_error", token=token[:16], error=str(e)[:100])
            return {"passed": False, "skip_reason": "activity_check_error", "last_activity_age_minutes": -1, "events_15m": 0, "unique_wallets_15m": 0}
        finally:
            await session.close()

    async def _check_whale_concentration(self, token: str) -> float | None:
        """Check top wallet concentration for a token.

        Returns concentration ratio (0.0-1.0) or None if data unavailable.
        """
        if not self._session_factory:
            return None

        session = self._session_factory()
        try:
            # Get total position size for this token
            total_stmt = (
                select(func.sum(WalletPosition.position_size))
                .where(WalletPosition.token_mint == token)
            )
            total_result = await session.execute(total_stmt)
            total_size = total_result.scalar()

            if not total_size or total_size <= 0:
                logger.info("paper.concentration_unavailable", token=token[:16])
                return None

            # Get top wallet position size
            top_stmt = (
                select(func.max(WalletPosition.position_size))
                .where(WalletPosition.token_mint == token)
            )
            top_result = await session.execute(top_stmt)
            top_size = top_result.scalar() or 0

            concentration = top_size / total_size if total_size > 0 else 0
            return concentration

        except Exception as e:
            logger.warning("paper.concentration_check_error", token=token[:16], error=str(e)[:100])
            return None
        finally:
            await session.close()

    # ── Price Fetching ──────────────────────────────────────

    async def _fetch_price(self, token_mint: str) -> float | None:
        """Fetch current price for a token via PricingService."""
        if not self._pricing:
            return None
        try:
            price_obj = await self._pricing.get_price(token_mint)
            if price_obj and price_obj.price:
                self._price_success_count += 1
                return float(price_obj.price)
            else:
                self._price_failure_count += 1
                if token_mint not in self._price_unavailable_tokens:
                    self._price_unavailable_tokens.append(token_mint)
                    # Keep only last 20 unavailable tokens
                    if len(self._price_unavailable_tokens) > 20:
                        self._price_unavailable_tokens = self._price_unavailable_tokens[-20:]
        except Exception as e:
            self._price_failure_count += 1
            logger.warning("paper.price_fetch_error", token=token_mint[:16], error=str(e)[:100])
        return None

    # ── DB Persistence ──────────────────────────────────────

    async def _persist_skipped(
        self,
        token: str,
        score: float,
        rank: int,
        reason: str,
        candidate: dict[str, Any],
        activity_data: dict[str, Any] | None = None,
    ) -> None:
        """Persist a SKIPPED candidate record for visibility.

        Deduplicates: if the same token was already SKIPPED for the same reason
        within the last ranking window, skip the insert to reduce noise.
        """
        if not self._session_factory:
            return

        session = self._session_factory()
        try:
            # Dedup check: same token + same reason within last window
            window_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.RANKING_WINDOW_MINUTES
            )
            dedup_stmt = (
                select(func.count())
                .select_from(PaperPosition)
                .where(
                    PaperPosition.token_mint == token,
                    PaperPosition.status == "SKIPPED",
                    PaperPosition.created_at >= window_cutoff,
                    PaperPosition.metadata_json["skip_reason"].as_string() == reason,
                )
            )
            dedup_result = await session.execute(dedup_stmt)
            if (dedup_result.scalar() or 0) > 0:
                return

            record = PaperPosition(
                id=uuid.uuid4(),
                token_mint=token,
                entry_score=score,
                virtual_size_usd=0,
                status="SKIPPED",
                opened_at=datetime.now(timezone.utc),
                metadata_json={
                    "rank": rank,
                    "skip_reason": reason,
                    "regime": candidate.get("regime", ""),
                    "stage": candidate.get("stage", ""),
                    "alpha_score": candidate.get("alpha_score", 0),
                    "confidence": candidate.get("confidence", 0),
                    **({"token_activity": activity_data} if activity_data else {}),
                },
            )
            session.add(record)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("paper.persist_skipped_error", token=token[:16], error=str(e))
        finally:
            await session.close()

    async def _persist_open_position(
        self,
        token: str,
        score: float,
        rank: int,
        entry_price: float,
        candidate: dict[str, Any],
        entry_timing: dict[str, Any] | None = None,
    ) -> None:
        """Persist an OPEN paper position."""
        if not self._session_factory:
            return

        # Position size = virtual_capital * risk_per_trade
        position_size_usd = settings.PAPER_VIRTUAL_CAPITAL * settings.PAPER_RISK_PER_TRADE

        session = self._session_factory()
        try:
            metadata = {
                "rank": rank,
                "regime": candidate.get("regime", ""),
                "stage": candidate.get("stage", ""),
                "alpha_score": candidate.get("alpha_score", 0),
                "confidence": candidate.get("confidence", 0),
                "signals": candidate.get("signals", {}),
                "momentum": (candidate.get("signals", {}) or {}).get("token_momentum", 0) or (candidate.get("signals", {}) or {}).get("momentum", 0),
                "token_momentum": (candidate.get("signals", {}) or {}).get("token_momentum", 0),
                "wallet_quality_momentum": (candidate.get("signals", {}) or {}).get("wallet_quality_momentum", 0),
                "smart_money": (candidate.get("signals", {}) or {}).get("smart_money", 0),
                "trailing_stop_active": False,
                "trailing_stop_level": 0,
            }
            if entry_timing:
                metadata["entry_timing"] = entry_timing

            record = PaperPosition(
                id=uuid.uuid4(),
                token_mint=token,
                entry_score=score,
                entry_price=entry_price,
                virtual_size_usd=round(position_size_usd, 2),
                status="OPEN",
                opened_at=datetime.now(timezone.utc),
                metadata_json=metadata,
            )
            session.add(record)
            await session.commit()

            logger.info(
                "paper.position_opened",
                token=token[:16],
                entry_price=entry_price,
                score=score,
                rank=rank,
                size_usd=round(position_size_usd, 2),
            )
        except Exception as e:
            await session.rollback()
            logger.error("paper.persist_open_error", token=token[:16], error=str(e))
        finally:
            await session.close()

    async def _count_open_positions(self) -> int:
        """Count currently OPEN positions."""
        if not self._session_factory:
            return 0
        session = self._session_factory()
        try:
            stmt = select(func.count()).select_from(PaperPosition).where(
                PaperPosition.status == "OPEN"
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
        finally:
            await session.close()

    async def _has_open_position(self, token: str) -> bool:
        """Check if we already have an OPEN position for this token."""
        if not self._session_factory:
            return False
        session = self._session_factory()
        try:
            stmt = select(func.count()).select_from(PaperPosition).where(
                PaperPosition.token_mint == token,
                PaperPosition.status == "OPEN",
            )
            result = await session.execute(stmt)
            return (result.scalar() or 0) > 0
        finally:
            await session.close()

    # ── Snapshots ───────────────────────────────────────────

    def _should_snapshot(self, now: datetime) -> bool:
        """Check if it's time for a portfolio snapshot."""
        if self._last_snapshot is None:
            return True
        interval = timedelta(seconds=settings.PAPER_SNAPSHOT_INTERVAL_SECONDS)
        return (now - self._last_snapshot) >= interval

    async def _take_snapshot(self, now: datetime) -> None:
        """Take a portfolio snapshot and persist to DB."""
        if not self._session_factory:
            return

        session = self._session_factory()
        try:
            # Count positions by status
            open_count = await self._count_open_in_session(session)
            closed_count = await self._count_closed_in_session(session)
            skipped_count = await self._count_skipped_in_session(session)

            # Sum realized PnL from closed outcomes
            realized_pnl = await self._sum_realized_pnl(session)

            # Compute unrealized PnL from open positions
            unrealized_pnl = 0.0
            open_stmt = select(PaperPosition).where(PaperPosition.status == "OPEN")
            result = await session.execute(open_stmt)
            open_positions = result.scalars().all()
            for pos in open_positions:
                meta = pos.metadata_json or {}
                current_roi = meta.get("current_roi")
                if current_roi is not None and pos.virtual_size_usd:
                    unrealized_pnl += pos.virtual_size_usd * (current_roi / 100)

            virtual_capital = settings.PAPER_VIRTUAL_CAPITAL
            portfolio_value = virtual_capital + realized_pnl + unrealized_pnl

            snapshot = PaperPortfolioSnapshot(
                id=uuid.uuid4(),
                portfolio_value=round(portfolio_value, 4),
                cash_balance=round(virtual_capital, 4),
                open_positions_count=open_count,
                unrealized_pnl=round(unrealized_pnl, 4),
                realized_pnl=round(realized_pnl, 4),
                created_at=now,
            )
            session.add(snapshot)
            await session.commit()

            logger.info(
                "paper.snapshot_taken",
                portfolio_value=round(portfolio_value, 2),
                open=open_count,
                closed=closed_count,
                realized_pnl=round(realized_pnl, 4),
                unrealized_pnl=round(unrealized_pnl, 4),
            )
        except Exception as e:
            await session.rollback()
            logger.error("paper.snapshot_error", error=str(e))
        finally:
            await session.close()

    # ── Price Snapshot Helpers ─────────────────────────────

    def _should_price_snapshot(self, now: datetime) -> bool:
        """Check if it's time for a price snapshot of open positions."""
        if self._last_price_snapshot is None:
            return True
        interval = timedelta(seconds=settings.PRICE_SNAPSHOT_INTERVAL_SECONDS)
        return (now - self._last_price_snapshot) >= interval

    def _should_run_retention(self, now: datetime) -> bool:
        """Check if it's time to run snapshot retention (hourly)."""
        if self._last_retention_run is None:
            return True
        return (now - self._last_retention_run) >= timedelta(hours=1)

    async def _capture_candidate_snapshot(self, token: str, candidate: dict[str, Any]) -> None:
        """Capture price snapshot for a paper candidate. Non-fatal."""
        if not self._snapshot_service or not self._session_factory:
            return
        session = self._session_factory()
        try:
            await self._snapshot_service.capture_for_paper_candidate(
                session, token, candidate_metadata=candidate
            )
        except Exception as e:
            logger.debug("paper.snapshot_candidate_error", token=token[:16], error=str(e)[:100])
        finally:
            await session.close()

    async def _check_entry_timing(
        self, token: str, entry_price: float
    ) -> dict[str, Any]:
        """Check entry timing using price snapshot history.

        Returns:
            dict with keys: passed, skip_reason, metrics (dict), warnings (list)
        """
        result: dict[str, Any] = {
            "passed": True,
            "skip_reason": "",
            "metrics": None,
            "warnings": [],
        }

        if not settings.PAPER_ENTRY_TIMING_ENABLED:
            return result

        if not self._session_factory:
            return result

        session = self._session_factory()
        try:
            from app.analytics.entry_timing import EntryTimingAnalyzer

            analyzer = EntryTimingAnalyzer(session)
            metrics = await analyzer.compute(
                token_mint=token,
                entry_time=datetime.now(timezone.utc),
                entry_price=entry_price,
            )
            result["metrics"] = metrics.to_dict()

            # Rule 1: insufficient history
            if metrics.data_quality == "insufficient_history":
                result["warnings"].append("insufficient_entry_timing_history")
                if settings.PAPER_ENTRY_TIMING_BLOCK_ON_INSUFFICIENT_HISTORY:
                    result["passed"] = False
                    result["skip_reason"] = "insufficient_entry_timing_history"
                logger.info(
                    "paper.entry_timing_insufficient",
                    token=token[:16],
                    data_quality=metrics.data_quality,
                )
                return result

            # Rule 2: late entry — too far from local low
            dist = metrics.entry_distance_from_local_low_pct
            if dist is not None and dist >= settings.PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT:
                result["passed"] = False
                result["skip_reason"] = "late_entry_risk"
                result["warnings"].append("late_entry_risk")
                logger.info(
                    "paper.entry_timing_late_entry",
                    token=token[:16],
                    distance_from_low=dist,
                    threshold=settings.PAPER_LATE_ENTRY_MAX_DISTANCE_FROM_LOW_PCT,
                )
                return result

            # Rule 3: chasing pump — 15m change too high
            change_15m = metrics.price_change_15m_pct
            if change_15m is not None and change_15m >= settings.PAPER_CHASING_PUMP_WAIT_CHANGE_15M_PCT:
                result["passed"] = False
                result["skip_reason"] = "chasing_pump_risk_15m"
                result["warnings"].append("chasing_pump_risk")
                logger.info(
                    "paper.entry_timing_chasing_15m",
                    token=token[:16],
                    change_15m=change_15m,
                    threshold=settings.PAPER_CHASING_PUMP_WAIT_CHANGE_15M_PCT,
                )
                return result

            # Rule 4: chasing pump — 30m change too high
            change_30m = metrics.price_change_30m_pct
            if change_30m is not None and change_30m >= settings.PAPER_CHASING_PUMP_WAIT_CHANGE_30M_PCT:
                result["passed"] = False
                result["skip_reason"] = "chasing_pump_risk_30m"
                result["warnings"].append("chasing_pump_risk")
                logger.info(
                    "paper.entry_timing_chasing_30m",
                    token=token[:16],
                    change_30m=change_30m,
                    threshold=settings.PAPER_CHASING_PUMP_WAIT_CHANGE_30M_PCT,
                )
                return result

        except Exception as e:
            # Entry timing failure must never crash the worker
            result["warnings"].append(f"entry_timing_error:{type(e).__name__}")
            logger.warning("paper.entry_timing_error", token=token[:16], error=str(e)[:200])
        finally:
            await session.close()

        return result

    async def _capture_open_position_snapshots(self) -> None:
        """Capture price snapshots for all open positions. Non-fatal."""
        if not self._snapshot_service or not self._session_factory:
            return
        session = self._session_factory()
        try:
            # Get open position token mints
            stmt = select(PaperPosition.token_mint).where(PaperPosition.status == "OPEN")
            result = await session.execute(stmt)
            tokens = [row[0] for row in result.fetchall()]
            if tokens:
                await self._snapshot_service.capture_for_open_positions(session, tokens)
        except Exception as e:
            logger.debug("paper.snapshot_open_error", error=str(e)[:100])
        finally:
            await session.close()

    async def _run_snapshot_retention(self) -> None:
        """Run price snapshot retention cleanup. Non-fatal."""
        if not self._snapshot_service or not self._session_factory:
            return
        session = self._session_factory()
        try:
            await self._snapshot_service.run_retention(session)
        except Exception as e:
            logger.debug("paper.snapshot_retention_error", error=str(e)[:100])
        finally:
            await session.close()

    async def _count_open_in_session(self, session: Any) -> int:
        stmt = select(func.count()).select_from(PaperPosition).where(
            PaperPosition.status == "OPEN"
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def _count_closed_in_session(self, session: Any) -> int:
        stmt = select(func.count()).select_from(PaperPosition).where(
            PaperPosition.status == "CLOSED"
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def _count_skipped_in_session(self, session: Any) -> int:
        stmt = select(func.count()).select_from(PaperPosition).where(
            PaperPosition.status == "SKIPPED"
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def _sum_realized_pnl(self, session: Any) -> float:
        stmt = select(func.coalesce(func.sum(PaperTradeOutcome.pnl_usd), 0.0))
        result = await session.execute(stmt)
        return float(result.scalar() or 0.0)

    # ── Status (for API) ────────────────────────────────────

    async def get_status(self) -> dict[str, Any]:
        """Get paper trading status for API endpoint."""
        if not self._session_factory:
            return self._empty_status()

        session = self._session_factory()
        try:
            open_count = await self._count_open_in_session(session)
            closed_count = await self._count_closed_in_session(session)
            skipped_count = await self._count_skipped_in_session(session)
            realized_pnl = await self._sum_realized_pnl(session)

            # Latest candidates (last 10 SKIPPED for visibility)
            latest_stmt = (
                select(PaperPosition)
                .where(PaperPosition.status == "SKIPPED")
                .order_by(PaperPosition.created_at.desc())
                .limit(10)
            )
            latest_result = await session.execute(latest_stmt)
            latest_skipped = latest_result.scalars().all()

            candidates = []
            skip_reasons = {}
            for pos in latest_skipped:
                meta = pos.metadata_json or {}
                candidates.append({
                    "token": pos.token_mint,
                    "score": pos.entry_score,
                    "rank": meta.get("rank", 0),
                    "regime": meta.get("regime", ""),
                    "stage": meta.get("stage", ""),
                    "skip_reason": meta.get("skip_reason", ""),
                    "created_at": pos.created_at.isoformat() if pos.created_at else "",
                })
                reason = meta.get("skip_reason", "unknown")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

            # Last snapshot
            snapshot_stmt = (
                select(PaperPortfolioSnapshot)
                .order_by(PaperPortfolioSnapshot.created_at.desc())
                .limit(1)
            )
            snapshot_result = await session.execute(snapshot_stmt)
            last_snapshot = snapshot_result.scalar_one_or_none()

            virtual_capital = settings.PAPER_VIRTUAL_CAPITAL

            return {
                "enabled": settings.PAPER_TRADING_ENABLED,
                "dry_run": settings.PAPER_TRADING_DRY_RUN,
                "open_positions": open_count,
                "closed_positions": closed_count,
                "skipped_positions": skipped_count,
                "latest_candidates": candidates,
                "latest_skip_reasons": skip_reasons,
                "portfolio_value": round(virtual_capital + realized_pnl, 2),
                "realized_pnl": round(realized_pnl, 4),
                "last_snapshot_time": (
                    last_snapshot.created_at.isoformat()
                    if last_snapshot and last_snapshot.created_at
                    else None
                ),
                "virtual_capital": virtual_capital,
                "cycle_count": self._cycle_count,
                "latest_price_success_count": self._price_success_count,
                "latest_price_failure_count": self._price_failure_count,
                "latest_price_unavailable_tokens": self._price_unavailable_tokens[-5:],
            }
        finally:
            await session.close()

    def _empty_status(self) -> dict[str, Any]:
        """Return empty status when no session factory."""
        return {
            "enabled": settings.PAPER_TRADING_ENABLED,
            "dry_run": settings.PAPER_TRADING_DRY_RUN,
            "open_positions": 0,
            "closed_positions": 0,
            "skipped_positions": 0,
            "latest_candidates": [],
            "latest_skip_reasons": {},
            "portfolio_value": 0,
            "realized_pnl": 0,
            "last_snapshot_time": None,
            "virtual_capital": 0,
            "cycle_count": self._cycle_count,
            "latest_price_success_count": self._price_success_count,
            "latest_price_failure_count": self._price_failure_count,
            "latest_price_unavailable_tokens": self._price_unavailable_tokens[-5:],
        }
