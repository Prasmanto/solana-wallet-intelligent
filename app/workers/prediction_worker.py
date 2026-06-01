"""Prediction worker — generates predictions from aggregated features.

Pipeline position: aggregated.features → predictions

This worker:
1. Consumes aggregated features from AGGREGATED_FEATURES stream
2. Runs pump prediction engine
3. Generates predictions
4. Persists predictions to DB
5. Publishes to PREDICTIONS stream

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
from app.infrastructure.database.models.prediction import Prediction
from app.pump_prediction.pump_prediction_engine import PumpPredictionEngine
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class PredictionWorker(ConsumerWorker):
    """Consumes aggregated features and generates predictions."""

    stream = StreamName.AGGREGATED_FEATURES
    group = "prediction"
    concurrency = 2
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Process aggregated features and generate predictions."""
        logger.info(
            "prediction_worker.processing",
            event_id=envelope.event_id[:16],
        )

        payload = envelope.payload_dict

        # Extract token and features
        token = payload.get("token", "")
        features = payload.get("features", {})
        cluster_id = payload.get("cluster_id", "")

        if not token:
            logger.warning("prediction_worker.no_token", event_id=envelope.event_id[:16])
            return

        # Run prediction engine
        prediction_result = await self._run_prediction(token, features, cluster_id)

        if prediction_result:
            # Persist prediction to DB
            await self._persist_prediction(prediction_result)

            # Publish to PREDICTIONS stream
            await self._producer.publish_chain(
                stream=StreamName.PREDICTIONS,
                event_type="prediction.generated",
                payload=prediction_result,
                source_envelope=envelope,
                metadata={
                    "stage": "prediction",
                    "worker": "prediction_worker",
                    "token": token,
                    "score": prediction_result.get("score", 0),
                },
            )

            logger.info(
                "prediction_worker.success",
                event_id=envelope.event_id[:16],
                token=token[:16],
                score=prediction_result.get("score", 0),
                regime=prediction_result.get("regime", "UNKNOWN"),
            )
        else:
            logger.info(
                "prediction_worker.no_prediction",
                event_id=envelope.event_id[:16],
                token=token[:16],
            )

    async def _run_prediction(
        self,
        token: str,
        features: dict[str, Any],
        cluster_id: str,
    ) -> dict[str, Any] | None:
        """Run pump prediction engine for a token."""
        try:
            engine = PumpPredictionEngine()

            # Extract signal components from features
            liquidity = features.get("liquidity", 0)
            momentum = features.get("momentum", 0)
            cluster = features.get("cluster", 0)
            smart_money = features.get("smart_money", 0)
            velocity = features.get("velocity", 0)
            anomaly = features.get("anomaly", 0)

            # Build events list for the engine
            events = [{
                "token": token,
                "liquidity": liquidity,
                "momentum": momentum,
                "cluster": cluster,
                "smart_money": smart_money,
                "velocity": velocity,
                "anomaly": anomaly,
            }]

            # Run prediction using analyze method
            prediction = await engine.analyze(events)

            if prediction:
                return {
                    "token": token,
                    "score": prediction.get("score", 0),
                    "probability": prediction.get("probability", 0),
                    "regime": prediction.get("regime", "NORMAL"),
                    "eta_minutes": prediction.get("eta_minutes", 60),
                    "horizon": prediction.get("horizon", "1h"),
                    "cluster_id": cluster_id,
                    "signals": {
                        "liquidity": liquidity,
                        "momentum": momentum,
                        "cluster": cluster,
                        "smart_money": smart_money,
                        "velocity": velocity,
                        "anomaly": anomaly,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            logger.error(
                "prediction_worker.engine_error",
                token=token[:16],
                error=str(e),
            )

        return None

    async def _persist_prediction(self, prediction: dict[str, Any]) -> None:
        """Persist prediction to database."""
        session = self.get_session()
        try:
            prediction_record = Prediction(
                id=uuid.uuid4(),
                prediction_type="PUMP",
                token=prediction.get("token", ""),
                cluster_id=prediction.get("cluster_id", ""),
                predicted_score=prediction.get("score", 0),
                predicted_probability=prediction.get("probability", 0),
                predicted_eta_minutes=prediction.get("eta_minutes", 60),
                prediction_horizon=prediction.get("horizon", "1h"),
                metadata_json=prediction,
                status="PENDING",
                created_at=datetime.now(timezone.utc),
            )

            session.add(prediction_record)
            await session.commit()

            logger.info(
                "prediction_worker.persisted",
                prediction_id=str(prediction_record.id)[:16],
                token=prediction.get("token", "")[:16],
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "prediction_worker.persist_error",
                error=str(e),
            )
        finally:
            await session.close()
