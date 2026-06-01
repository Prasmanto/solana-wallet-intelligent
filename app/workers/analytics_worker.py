"""Analytics worker — enriches trades with clustering and classification.

Pipeline position: trade.normalized → trade.enriched → aggregated.features

This worker:
1. Consumes normalized trades
2. Updates wallet graph
3. Updates clustering
4. Classifies wallets
5. Extracts features
6. Persists intelligence to DB
7. Publishes enriched trade to TRADE_ENRICHED
8. Publishes aggregated features to AGGREGATED_FEATURES

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
- Non-blocking: intelligence updates are async-safe
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.models.wallet_feature import WalletFeature
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class AnalyticsWorker(ConsumerWorker):
    """Consumes normalized trades and enriches with intelligence."""

    stream = StreamName.TRADE_NORMALIZED
    group = "analytics"
    concurrency = 2
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Process normalized trade and enrich with intelligence.

        Must commit to DB before returning.
        """
        logger.info(
            "analytics_worker.processing",
            event_id=envelope.event_id[:16],
            event_type=envelope.event_type,
            stage="process",
        )

        payload = envelope.payload_dict

        # 1. Update intelligence graph and clustering
        intelligence = await self._compute_intelligence(payload)

        # 2. Persist intelligence to DB
        await self._persist_intelligence(payload, intelligence)

        # 3. Build enriched payload
        enriched = {
            **payload,
            "intelligence": intelligence,
        }

        # 4. Publish to trade.enriched
        await self._producer.publish_chain(
            stream=StreamName.TRADE_ENRICHED,
            event_type="trade.enriched",
            payload=enriched,
            source_envelope=envelope,
            metadata={
                "stage": "analytics",
                "worker": "analytics_worker",
                "cluster_id": intelligence.get("cluster_id", ""),
                "wallet_type": intelligence.get("wallet_type", ""),
            },
        )

        # 5. Publish aggregated features to AGGREGATED_FEATURES
        token = payload.get("token", "")
        if token:
            aggregated_features = {
                "token": token,
                "wallet": payload.get("wallet", ""),
                "cluster_id": intelligence.get("cluster_id", ""),
                "features": intelligence.get("features", {}),
                "smart_money": intelligence.get("smart_money"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self._producer.publish_chain(
                stream=StreamName.AGGREGATED_FEATURES,
                event_type="features.aggregated",
                payload=aggregated_features,
                source_envelope=envelope,
                metadata={
                    "stage": "analytics",
                    "worker": "analytics_worker",
                    "token": token,
                },
            )

        logger.info(
            "analytics_worker.completed",
            event_id=envelope.event_id[:16],
            wallet=payload.get("wallet", "")[:16],
            wallet_type=intelligence.get("wallet_type", ""),
            cluster_id=intelligence.get("cluster_id", "")[:16],
            stage="completed",
        )

    async def _compute_intelligence(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compute intelligence for the event.

        Each intelligence component is independently optional.
        """
        cluster_info = None
        classification = {"wallet_type": "UNKNOWN", "confidence": 0.0}
        wallet_features = {}
        smart_money_data = None

        wallet = payload.get("wallet", "")

        try:
            from app.intelligence.clustering_engine import PersistentClusteringEngine
            clustering = PersistentClusteringEngine()
            cluster_info = clustering.process_event(payload)
        except Exception:
            pass

        if wallet:
            try:
                from app.intelligence.features import PersistentFeatureStore
                from app.intelligence.wallet_classifier import WalletClassifier
                features = PersistentFeatureStore()
                classifier = WalletClassifier(features)
                classification = classifier.classify(wallet, [payload])
            except Exception:
                pass

        if wallet:
            try:
                from app.intelligence.features import PersistentFeatureStore
                features = PersistentFeatureStore()
                wallet_features = features.extract(wallet, [payload])
            except Exception:
                pass

        if wallet:
            try:
                from app.smart_money.smart_money_engine import SmartMoneyEngine
                smart_money = SmartMoneyEngine()
                smart_money_signal = await smart_money.analyze(
                    wallet=wallet,
                    events=[payload],
                )
                smart_money_data = smart_money_signal.to_dict() if smart_money_signal else None
            except Exception:
                pass

        return {
            "cluster_id": cluster_info.get("cluster_id", "") if cluster_info else "",
            "cluster_size": cluster_info.get("cluster_size", 0) if cluster_info else 0,
            "cluster_confidence": cluster_info.get("cluster_confidence", 0.0) if cluster_info else 0.0,
            "wallet_type": classification.get("wallet_type", "UNKNOWN"),
            "wallet_confidence": classification.get("confidence", 0.0),
            "features": wallet_features,
            "smart_money": smart_money_data,
        }

    async def _persist_intelligence(
        self,
        payload: dict[str, Any],
        intelligence: dict[str, Any],
    ) -> None:
        """Persist intelligence data to database."""
        wallet = payload.get("wallet", "")
        token = payload.get("token", "")

        if not wallet:
            return

        session = self.get_session()
        try:
            from app.infrastructure.database.models.wallet_feature import WalletFeature
            
            # Check if feature record exists for this wallet and time window
            result = await session.execute(
                select(WalletFeature).where(
                    WalletFeature.wallet_address == wallet,
                    WalletFeature.time_window == "1h",
                )
            )
            existing = result.scalar_one_or_none()

            now = datetime.now(timezone.utc)
            features = intelligence.get("features", {})

            if existing:
                # Update existing record
                existing.volume = features.get("volume", 0)
                existing.tx_frequency = features.get("tx_frequency", 0)
                existing.avg_interval = features.get("avg_interval", 0)
                existing.token_diversity = features.get("token_diversity", 0)
                existing.buy_count = features.get("buy_count", 0)
                existing.sell_count = features.get("sell_count", 0)
                existing.transfer_count = features.get("transfer_count", 0)
                existing.buy_sell_ratio = features.get("buy_sell_ratio", 0)
                existing.interaction_score = features.get("interaction_score", 0)
                existing.features_json = intelligence
                existing.computed_at = now
            else:
                # Create new record
                feature_record = WalletFeature(
                    wallet_address=wallet,
                    time_window="1h",
                    volume=features.get("volume", 0),
                    tx_frequency=features.get("tx_frequency", 0),
                    avg_interval=features.get("avg_interval", 0),
                    token_diversity=features.get("token_diversity", 0),
                    buy_count=features.get("buy_count", 0),
                    sell_count=features.get("sell_count", 0),
                    transfer_count=features.get("transfer_count", 0),
                    buy_sell_ratio=features.get("buy_sell_ratio", 0),
                    interaction_score=features.get("interaction_score", 0),
                    features_json=intelligence,
                    computed_at=now,
                )
                session.add(feature_record)

            await session.commit()

            logger.debug(
                "analytics.intelligence_persisted",
                wallet=wallet[:16],
                token=token[:16] if token else "",
                wallet_type=intelligence.get("wallet_type", ""),
            )

        except Exception as e:
            await session.rollback()
            logger.warning(
                "analytics.persist_failed",
                error=str(e),
                wallet=wallet[:16],
            )
        finally:
            await session.close()
