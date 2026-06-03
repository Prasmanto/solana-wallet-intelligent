"""Ranking worker — ranks tokens based on predictions and signals.

Pipeline position: predictions → rankings

This worker:
1. Consumes predictions from PREDICTIONS stream
2. Skips INVALID predictions (pre-repair collapsed)
3. Persists ranking to DB (token_rankings table)
4. Periodically computes batch ranks over a sliding window
5. Publishes to RANKINGS stream
6. Runs retention cleanup on old rankings

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import delete, func, select, text

from app.config.settings import settings
from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.models.token_ranking import TokenRanking
from app.ranking.token_ranker import TokenRankingEngine
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)

# Stablecoins and wrapped SOL to skip in paper trading
_SKIP_TOKENS = set(settings.PAPER_SKIP_TOKENS)


class RankingWorker(ConsumerWorker):
    """Consumes predictions and generates token rankings."""

    stream = StreamName.PREDICTIONS
    group = "ranking"
    concurrency = 2
    block_ms = 5000

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_rank_batch: datetime | None = None
        self._last_retention_run: datetime | None = None
        self._paper_worker: Any = None
        # Price snapshot integration
        self._snapshot_service: Any = None
        self._last_ranked_snapshot: datetime | None = None

    async def process(self, envelope: EventEnvelope) -> None:
        """Process prediction and generate rankings."""
        logger.info(
            "ranking_worker.processing",
            event_id=envelope.event_id[:16],
        )

        payload = envelope.payload_dict

        # Extract prediction data
        token = payload.get("token", "")
        score = payload.get("score", 0)
        regime = payload.get("regime", "NORMAL")
        signals = payload.get("signals", {})
        cluster_id = payload.get("cluster_id", "")
        stage = payload.get("stage", "EARLY_STAGE")
        conviction = payload.get("conviction", 0)
        prediction_id = payload.get("prediction_id", "")

        if not token:
            logger.warning("ranking_worker.no_token", event_id=envelope.event_id[:16])
            return

        # Skip invalid predictions (pre-repair collapsed)
        invalid_reason = payload.get("invalid_reason", "")
        if invalid_reason == "collapsed_pre_repair_feature_mismatch":
            logger.info(
                "ranking_worker.skipped_invalid",
                event_id=envelope.event_id[:16],
                token=token[:16],
            )
            return

        # Skip if score is exactly the collapsed value with no signals
        if score == 0.0592 and not any(v > 0 for v in signals.values() if isinstance(v, (int, float))):
            logger.info(
                "ranking_worker.skipped_collapsed",
                event_id=envelope.event_id[:16],
                token=token[:16],
            )
            return

        # Run ranking engine
        ranking_result = await self._run_ranking(
            token, score, regime, signals, cluster_id
        )

        # Build the output — use engine result or fall back to prediction-derived ranking
        if ranking_result:
            output = ranking_result
        else:
            output = {
                "token": token,
                "alpha_score": score,
                "regime": regime,
                "is_leader": False,
                "lead_strength_score": 0,
                "smart_money_flag": any(
                    signals.get(k, 0) > 0.5
                    for k in ("smart_money", "liquidity")
                    if isinstance(signals.get(k), (int, float))
                ),
                "confidence": conviction,
                "signals": signals,
                "cluster_id": cluster_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if output:
            # Persist to DB
            ranking_id = await self._persist_ranking(
                ranking_result=output,
                score=score,
                stage=stage,
                conviction=conviction,
                prediction_id=prediction_id,
            )

            # Publish to RANKINGS stream
            output["ranking_id"] = str(ranking_id) if ranking_id else ""
            await self._producer.publish_chain(
                stream=StreamName.RANKINGS,
                event_type="ranking.generated",
                payload=output,
                source_envelope=envelope,
                metadata={
                    "stage": "ranking",
                    "worker": "ranking_worker",
                    "token": token,
                    "rank": output.get("rank", 0),
                    "alpha_score": output.get("alpha_score", 0),
                },
            )

            logger.info(
                "ranking_worker.success",
                event_id=envelope.event_id[:16],
                token=token[:16],
                rank=output.get("rank", 0),
                alpha_score=output.get("alpha_score", 0),
                ranking_id=str(ranking_id)[:16] if ranking_id else "",
            )
        else:
            logger.info(
                "ranking_worker.no_ranking",
                event_id=envelope.event_id[:16],
                token=token[:16],
            )

        # Periodic: compute batch ranks, emit paper candidates, run retention
        now = datetime.now(timezone.utc)
        if self._should_run_batch_ranks(now):
            await self._compute_batch_ranks(now)
            await self._emit_paper_candidates()
            self._last_rank_batch = now

        if self._should_run_retention(now):
            await self._run_retention(now)
            self._last_retention_run = now

    def _should_run_batch_ranks(self, now: datetime) -> bool:
        window = timedelta(minutes=settings.RANKING_WINDOW_MINUTES)
        if self._last_rank_batch is None:
            return True
        return (now - self._last_rank_batch) >= window

    def _should_run_retention(self, now: datetime) -> bool:
        if self._last_retention_run is None:
            return True
        return (now - self._last_retention_run) >= timedelta(hours=1)

    async def _compute_batch_ranks(self, now: datetime) -> None:
        """Compute batch ranks for all valid predictions in the current window.

        Queries the latest predictions, ranks them by score descending,
        and updates token_rankings with the computed rank and window.
        """
        session = self.get_session()
        try:
            window_start = now - timedelta(minutes=settings.RANKING_WINDOW_MINUTES)
            window_id = window_start.strftime("%Y-%m-%dT%H:%M")

            # Get top predictions in window, deduplicated by token (best score per token)
            stmt = text("""
                WITH ranked AS (
                    SELECT DISTINCT ON (token)
                        id, token, predicted_score, status,
                        metadata_json->>'regime' as regime,
                        metadata_json->>'stage' as stage,
                        metadata_json->>'cluster_id' as cluster_id,
                        metadata_json->'signals' as signals_json,
                        created_at
                    FROM predictions
                    WHERE created_at >= :window_start
                      AND status = 'PENDING'
                      AND token != ''
                    ORDER BY token, predicted_score DESC
                )
                SELECT *, ROW_NUMBER() OVER (ORDER BY predicted_score DESC) as batch_rank
                FROM ranked
                ORDER BY predicted_score DESC
                LIMIT :max_tokens
            """)

            result = await session.execute(
                stmt,
                {"window_start": window_start, "max_tokens": settings.RANKING_MAX_TOKENS},
            )
            rows = result.fetchall()

            if not rows:
                logger.info(
                    "ranking_worker.batch_ranks_empty",
                    window=window_id,
                )
                await session.close()
                return

            # Update existing rankings for this window with computed ranks
            updated = 0
            for row in rows:
                # Find existing ranking for this prediction_id in this window
                pred_id = row[0] if row[0] else None
                token = row[1]
                score = float(row[2]) if row[2] else 0
                regime = row[4] or "NORMAL"
                stage = row[5] or "EARLY_STAGE"
                signals_raw = row[7]  # metadata_json->'signals' from prediction
                batch_rank = int(row[9]) if row[9] else 0

                # Parse signals from prediction
                pred_signals = None
                if signals_raw:
                    try:
                        import json as _json
                        pred_signals = _json.loads(signals_raw) if isinstance(signals_raw, str) else signals_raw
                    except Exception:
                        pred_signals = None

                if not pred_id:
                    continue

                # Update existing ranking or create new one with rank
                existing_stmt = select(TokenRanking).where(
                    TokenRanking.prediction_id == pred_id,
                    TokenRanking.token_mint == token,
                )
                existing_result = await session.execute(existing_stmt)
                existing = existing_result.scalar_one_or_none()

                if existing:
                    existing.rank = batch_rank
                    existing.ranking_window = window_id
                    # Preserve signals from prediction if existing has none
                    if pred_signals and not existing.signals_json:
                        existing.signals_json = pred_signals
                    updated += 1
                else:
                    # Create ranking record from prediction
                    ranking_record = TokenRanking(
                        id=uuid.uuid4(),
                        token_mint=token,
                        score=score,
                        rank=batch_rank,
                        prediction_id=pred_id,
                        regime=regime,
                        stage=stage,
                        alpha_score=score,
                        is_leader=False,
                        confidence=0,
                        signals_json=pred_signals,
                        metadata_json={"batch_ranked": True},
                        ranking_window=window_id,
                        created_at=now,
                    )
                    session.add(ranking_record)
                    updated += 1

            await session.commit()

            logger.info(
                "ranking_worker.batch_ranks_done",
                window=window_id,
                tokens_ranked=len(rows),
                updated=updated,
                top_token=rows[0][1] if rows else "",
                top_score=float(rows[0][2]) if rows and rows[0][2] else 0,
            )

            # Capture price snapshots for ranked tokens (non-fatal)
            if self._should_ranked_snapshot(now):
                ranked_tokens = [
                    {"token_mint": row[1], "score": float(row[2]) if row[2] else 0, "rank": int(row[9]) if row[9] else 0}
                    for row in rows
                ]
                await self._capture_ranked_token_snapshots(ranked_tokens, now)
                self._last_ranked_snapshot = now

        except Exception as e:
            await session.rollback()
            logger.error(
                "ranking_worker.batch_ranks_error",
                error=str(e),
            )
        finally:
            await session.close()

    async def _emit_paper_candidates(self) -> None:
        """Emit paper trading candidates.

        Called after batch rank computation. Queries latest ranked tokens,
        filters by score/rank/regime, publishes to stream, and directly
        processes candidates via PaperTradingWorker.
        """
        if not settings.PAPER_TRADING_ENABLED:
            logger.debug("paper.emit_skipped", reason="paper_trading_disabled")
            return

        try:
            result = await get_paper_trading_candidates(
                session_factory=self._session_factory,
                min_score=settings.PAPER_ENTRY_SCORE_THRESHOLD,
                max_candidates=settings.PAPER_MAX_POSITIONS,
            )

            candidates = result.get("candidates", [])
            if not candidates:
                logger.info("paper.no_candidates")
                return

            emitted = 0
            for candidate in candidates:
                score = candidate.get("score", 0)
                rank = candidate.get("rank", 0)
                token = candidate.get("token", "")

                # Final filter: score and rank thresholds
                if score < settings.PAPER_ENTRY_SCORE_THRESHOLD:
                    continue
                if rank > settings.PAPER_MAX_RANK:
                    continue

                # Publish to stream (for observability)
                await self._producer.publish(
                    stream=StreamName.PAPER_TRADING,
                    event_type="paper.candidate",
                    payload=candidate,
                    metadata={
                        "stage": "paper_candidate",
                        "worker": "ranking_worker",
                        "token": token,
                        "score": score,
                        "rank": rank,
                    },
                )

                # Directly process via PaperTradingWorker
                if self._paper_worker:
                    await self._paper_worker.process_candidate(candidate)

                emitted += 1

            logger.info(
                "paper.candidates_emitted",
                emitted=emitted,
                threshold=settings.PAPER_ENTRY_SCORE_THRESHOLD,
                max_rank=settings.PAPER_MAX_RANK,
            )

        except Exception as e:
            logger.error("paper.emit_error", error=str(e))

    async def _run_retention(self, now: datetime) -> None:
        """Remove rankings older than RANKING_RETENTION_HOURS."""
        session = self.get_session()
        try:
            cutoff = now - timedelta(hours=settings.RANKING_RETENTION_HOURS)
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M")

            # Count rows to delete
            count_stmt = select(func.count()).select_from(TokenRanking).where(
                TokenRanking.created_at < cutoff
            )
            count_result = await session.execute(count_stmt)
            count = count_result.scalar() or 0

            if count == 0:
                logger.info("ranking_worker.retention_noop", cutoff=cutoff_str)
                await session.close()
                return

            # Delete old rankings
            delete_stmt = delete(TokenRanking).where(TokenRanking.created_at < cutoff)
            await session.execute(delete_stmt)
            await session.commit()

            logger.info(
                "ranking_worker.retention_done",
                deleted=count,
                cutoff=cutoff_str,
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "ranking_worker.retention_error",
                error=str(e),
            )
        finally:
            await session.close()

    # ── Price Snapshot Helpers ─────────────────────────────

    def _should_ranked_snapshot(self, now: datetime) -> bool:
        """Check if it's time for ranked token snapshots."""
        if self._last_ranked_snapshot is None:
            return True
        interval = timedelta(seconds=settings.PRICE_SNAPSHOT_INTERVAL_SECONDS)
        return (now - self._last_ranked_snapshot) >= interval

    async def _capture_ranked_token_snapshots(
        self, ranked_tokens: list[dict[str, Any]], now: datetime
    ) -> None:
        """Capture price snapshots for top-ranked tokens. Non-fatal."""
        # Lazy initialization of snapshot service
        if self._snapshot_service is None and settings.PRICE_SNAPSHOT_ENABLED:
            try:
                from redis.asyncio import Redis
                from app.analytics.pricing_service import PricingService
                from app.analytics.price_snapshot_service import PriceSnapshotService
                from app.infrastructure.external.jupiter_client import JupiterPriceClient
                from app.infrastructure.redis.price_cache import TokenPriceCache
                redis = Redis.from_url(settings.REDIS_CACHE_URL, decode_responses=True)
                jupiter = JupiterPriceClient()
                cache = TokenPriceCache(redis)
                pricing = PricingService(jupiter, cache)
                self._snapshot_service = PriceSnapshotService(pricing)
                logger.info("ranking.snapshot_service_initialized")
            except Exception as e:
                logger.warning("ranking.snapshot_init_failed", error=str(e)[:200])
                self._snapshot_service = False  # Sentinel: don't retry

        if not self._snapshot_service or self._snapshot_service is False:
            return

        session = self._session_factory()
        try:
            await self._snapshot_service.capture_for_ranked_tokens(session, ranked_tokens)
        except Exception as e:
            logger.warning("ranking.snapshot_error", error=str(e)[:200])
        finally:
            await session.close()

    async def _run_ranking(
        self,
        token: str,
        score: float,
        regime: str,
        signals: dict[str, Any],
        cluster_id: str,
    ) -> dict[str, Any] | None:
        """Run token ranking engine."""
        try:
            ranker = TokenRankingEngine()
            ranking = ranker.get_token_alpha(token=token)

            if ranking:
                return {
                    "token": token,
                    "alpha_score": ranking.get("alpha_score", 0),
                    "regime": regime,
                    "is_leader": ranking.get("is_leader", False),
                    "lead_strength_score": ranking.get("lead_strength_score", 0),
                    "smart_money_flag": ranking.get("smart_money_flag", False),
                    "confidence": ranking.get("confidence", 0),
                    "signals": signals,
                    "cluster_id": cluster_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            logger.error(
                "ranking_worker.engine_error",
                token=token[:16],
                error=str(e),
            )

        return None

    async def _persist_ranking(
        self,
        ranking_result: dict[str, Any],
        score: float,
        stage: str,
        conviction: float,
        prediction_id: str,
    ) -> uuid.UUID | None:
        """Persist ranking to token_rankings table."""
        session = self.get_session()
        try:
            pred_uuid = None
            if prediction_id:
                try:
                    pred_uuid = uuid.UUID(prediction_id)
                except (ValueError, AttributeError):
                    pass

            token = ranking_result.get("token", "")
            alpha_score = ranking_result.get("alpha_score", 0)
            rank = ranking_result.get("rank", 0)
            regime = ranking_result.get("regime", "NORMAL")
            is_leader = ranking_result.get("is_leader", False)
            confidence = ranking_result.get("confidence", 0)
            signals = ranking_result.get("signals", {})

            # Check for duplicate (same token + prediction_id)
            if pred_uuid:
                stmt = select(TokenRanking).where(
                    TokenRanking.prediction_id == pred_uuid,
                    TokenRanking.token_mint == token,
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                if existing:
                    logger.debug(
                        "ranking_worker.duplicate_skip",
                        token=token[:16],
                        prediction_id=str(pred_uuid)[:16],
                    )
                    await session.close()
                    return existing.id

            ranking_record = TokenRanking(
                id=uuid.uuid4(),
                token_mint=token,
                score=score,
                rank=rank,
                prediction_id=pred_uuid,
                regime=regime,
                stage=stage,
                alpha_score=alpha_score,
                is_leader=is_leader,
                confidence=confidence,
                signals_json=signals,
                metadata_json={
                    "conviction": conviction,
                    "lead_strength_score": ranking_result.get("lead_strength_score", 0),
                    "smart_money_flag": ranking_result.get("smart_money_flag", False),
                    "cluster_id": ranking_result.get("cluster_id", ""),
                },
                ranking_window="",
                created_at=datetime.now(timezone.utc),
            )

            session.add(ranking_record)
            await session.commit()

            return ranking_record.id

        except Exception as e:
            await session.rollback()
            logger.error(
                "ranking_worker.persist_error",
                token=ranking_result.get("token", "")[:16],
                error=str(e),
            )
            return None
        finally:
            await session.close()


async def get_paper_trading_candidates(
    session_factory,
    min_score: float | None = None,
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """Identify paper trading candidates from latest rankings.

    Dry-run by default — does NOT insert into paper_positions.

    Rules:
    - score >= threshold (default from settings)
    - rank <= 20
    - regime in PUMP_BUILDUP or PARABOLIC, or stage in HIGH_PUMP_RISK/PRE_PUMP
    - skip stablecoins/wrapped SOL
    - max candidates per cycle
    """
    from app.infrastructure.database.session import async_session_factory

    factory = session_factory or async_session_factory
    session = factory()
    threshold = min_score or settings.PAPER_ENTRY_SCORE_THRESHOLD

    try:
        # Get latest rankings with rank > 0 from most recent window
        stmt = text("""
            WITH latest_window AS (
                SELECT ranking_window, MAX(created_at) as max_created
                FROM token_rankings
                WHERE rank > 0
                  AND ranking_window != ''
                GROUP BY ranking_window
                ORDER BY max_created DESC
                LIMIT 1
            )
            SELECT tr.token_mint, tr.score, tr.rank, tr.regime, tr.stage,
                   tr.alpha_score, tr.confidence, tr.signals_json,
                   tr.created_at, tr.ranking_window
            FROM token_rankings tr
            JOIN latest_window lw ON tr.ranking_window = lw.ranking_window
            WHERE tr.score >= :threshold
              AND tr.rank <= 20
            ORDER BY tr.score DESC
            LIMIT :max_candidates
        """)

        result = await session.execute(
            stmt,
            {"threshold": threshold, "max_candidates": max_candidates * 3},
        )
        rows = result.fetchall()

        candidates = []
        skipped = []

        for row in rows:
            token = row[0]
            score = float(row[1]) if row[1] else 0
            rank = int(row[2]) if row[2] else 0
            regime = row[3] or "NORMAL"
            stage = row[4] or "EARLY_STAGE"

            # Skip stablecoins / wrapped SOL
            if token in _SKIP_TOKENS:
                skipped.append({"token": token, "reason": "skip_token_config"})
                continue

            # Must be in an active regime or stage
            active_regimes = {"PUMP_BUILDUP", "PARABOLIC"}
            active_stages = {"HIGH_PUMP_RISK", "PRE_PUMP", "ACCUMULATION_PHASE"}
            if regime not in active_regimes and stage not in active_stages:
                skipped.append({"token": token, "reason": f"low_activity_regime_{regime}"})
                continue

            candidates.append({
                "token": token,
                "score": score,
                "rank": rank,
                "regime": regime,
                "stage": stage,
                "alpha_score": float(row[5]) if row[5] else 0,
                "confidence": float(row[6]) if row[6] else 0,
                "signals": row[7] if row[7] else {},
                "created_at": row[8].isoformat() if row[8] else "",
                "ranking_window": row[9] or "",
            })

            if len(candidates) >= max_candidates:
                break

        logger.info(
            "paper.dry_run_candidates",
            candidates=len(candidates),
            skipped=len(skipped),
            threshold=threshold,
        )

        return {
            "candidates": candidates,
            "skipped": skipped,
            "total_evaluated": len(rows),
            "threshold": threshold,
            "dry_run": settings.PAPER_TRADING_DRY_RUN,
        }

    finally:
        await session.close()
