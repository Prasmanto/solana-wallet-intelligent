"""Aggregation worker — computes wallet metrics from position updates.

Pipeline position: trade.enriched → wallet.metrics → aggregated.features

This worker:
1. Consumes enriched trades from trade.enriched stream
2. Triggers wallet metrics aggregation
3. Persists computed metrics
4. Publishes metrics update event to AGGREGATED_FEATURES

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
"""

from __future__ import annotations

import structlog

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.repositories.position_repo import PositionRepository
from app.analytics.metrics_aggregator import MetricsAggregator
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class AggregationWorker(ConsumerWorker):
    """Consumes enriched trades and computes wallet metrics."""

    stream = StreamName.TRADE_ENRICHED
    group = "aggregation"
    concurrency = 2
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Process enriched trade and update wallet metrics."""
        logger.info(
            "aggregation_worker.processing",
            event_id=envelope.event_id[:16],
        )

        payload = envelope.payload_dict
        wallet = payload.get("wallet", "")
        token = payload.get("token", "")

        if not wallet:
            logger.warning("aggregation_worker.no_wallet", event_id=envelope.event_id[:16])
            return

        # Compute wallet metrics
        session = self.get_session()
        try:
            repo = PositionRepository(session)
            aggregator = MetricsAggregator(repo)

            result = await aggregator.compute_wallet_metrics(wallet)
            await session.commit()

            logger.info(
                "aggregation_worker.success",
                wallet=wallet[:8],
                positions=result.trades_processed,
                total_pnl=float(result.metrics.total_realized_pnl),
                win_rate=float(result.metrics.win_rate),
            )

            # Publish aggregated features to AGGREGATED_FEATURES stream
            # This enables prediction and ranking workers to consume
            aggregated_features = {
                "token": token,
                "wallet": wallet,
                "features": {
                    "total_pnl": float(result.metrics.total_realized_pnl),
                    "win_rate": float(result.metrics.win_rate),
                    "total_trades": result.metrics.total_trades,
                    "active_positions": result.metrics.active_positions,
                    "total_volume": float(result.metrics.total_volume),
                },
                "metrics": {
                    "total_realized_pnl": float(result.metrics.total_realized_pnl),
                    "total_realized_roi": float(result.metrics.total_realized_roi),
                    "win_rate": float(result.metrics.win_rate),
                    "total_trades": result.metrics.total_trades,
                },
                "timestamp": result.metrics.last_updated_at.isoformat() if result.metrics.last_updated_at else "",
            }

            await self._producer.publish_chain(
                stream=StreamName.AGGREGATED_FEATURES,
                event_type="metrics.aggregated",
                payload=aggregated_features,
                source_envelope=envelope,
                metadata={
                    "stage": "aggregation",
                    "worker": "aggregation_worker",
                    "wallet": wallet,
                    "token": token,
                },
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "aggregation_worker.error",
                wallet=wallet[:8],
                error=str(e),
            )
            raise
        finally:
            await session.close()
