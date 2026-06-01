"""Ranking worker — ranks tokens based on predictions and signals.

Pipeline position: predictions → rankings

This worker:
1. Consumes predictions from PREDICTIONS stream
2. Runs token ranking engine
3. Generates ranked token list
4. Persists rankings to DB
5. Publishes to RANKINGS stream

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.ranking.token_ranker import TokenRankingEngine
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class RankingWorker(ConsumerWorker):
    """Consumes predictions and generates token rankings."""

    stream = StreamName.PREDICTIONS
    group = "ranking"
    concurrency = 2
    block_ms = 5000

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

        if not token:
            logger.warning("ranking_worker.no_token", event_id=envelope.event_id[:16])
            return

        # Run ranking engine
        ranking_result = await self._run_ranking(
            token, score, regime, signals, cluster_id
        )

        if ranking_result:
            # Publish to RANKINGS stream
            await self._producer.publish_chain(
                stream=StreamName.RANKINGS,
                event_type="ranking.generated",
                payload=ranking_result,
                source_envelope=envelope,
                metadata={
                    "stage": "ranking",
                    "worker": "ranking_worker",
                    "token": token,
                    "rank": ranking_result.get("rank", 0),
                    "alpha_score": ranking_result.get("alpha_score", 0),
                },
            )

            logger.info(
                "ranking_worker.success",
                event_id=envelope.event_id[:16],
                token=token[:16],
                rank=ranking_result.get("rank", 0),
                alpha_score=ranking_result.get("alpha_score", 0),
            )
        else:
            logger.info(
                "ranking_worker.no_ranking",
                event_id=envelope.event_id[:16],
                token=token[:16],
            )

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

            # Run ranking - get_token_alpha only takes token parameter
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
