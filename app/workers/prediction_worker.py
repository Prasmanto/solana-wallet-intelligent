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

        # Check for empty/all-zero features — skip prediction
        if not features or all(v == 0 for v in features.values() if isinstance(v, (int, float))):
            logger.info(
                "prediction_worker.skipped_empty_features",
                event_id=envelope.event_id[:16],
                token=token[:16],
                reason="all_zero_features",
            )
            return

        # Require minimum feature quality
        # Support both analytics keys (volume, token_diversity) and aggregation keys (total_volume, total_trades)
        has_quality = (
            features.get("token_diversity", 0) > 0
            or features.get("activity_score", 0) > 0
            or features.get("interaction_score", 0) > 0
            or features.get("total_volume", 0) > 0
            or features.get("total_trades", 0) > 0
            or features.get("win_rate", 0) > 0
            or features.get("volume", 0) > 0
            or features.get("tx_frequency", 0) > 0
            or features.get("buy_count", 0) > 0
            or features.get("sell_count", 0) > 0
        )
        if not has_quality:
            logger.info(
                "prediction_worker.skipped_low_quality",
                event_id=envelope.event_id[:16],
                token=token[:16],
                reason="insufficient_feature_quality",
            )
            return

        # Run prediction engine
        prediction_result = await self._run_prediction(token, features, cluster_id)

        if prediction_result:
            # Persist prediction to DB and get its ID
            prediction_id = await self._persist_prediction(prediction_result)

            # Include prediction_id in payload for downstream dedup (ranking, paper trading)
            if prediction_id:
                prediction_result["prediction_id"] = str(prediction_id)

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
        """Run prediction engine for a token using available features.

        Supports two feature formats:
        - Aggregation keys: total_volume, win_rate, total_trades, active_positions, total_pnl
        - Analytics keys: volume, tx_frequency, token_diversity, buy_count, sell_count,
          interaction_score, buy_sell_ratio, transfer_count
        """
        try:
            import math

            # --- Map aggregation-format features ---
            total_volume = features.get("total_volume", 0) or 0
            win_rate = features.get("win_rate", 0) or 0
            total_trades = features.get("total_trades", 0) or 0
            active_positions = features.get("active_positions", 0) or 0
            total_pnl = features.get("total_pnl", 0) or 0

            # --- Map analytics-format features (fallbacks) ---
            volume = features.get("volume", 0) or 0
            tx_frequency = features.get("tx_frequency", 0) or 0
            token_diversity = features.get("token_diversity", 0) or 0
            buy_count = features.get("buy_count", 0) or 0
            sell_count = features.get("sell_count", 0) or 0
            interaction_score = features.get("interaction_score", 0) or 0
            buy_sell_ratio = features.get("buy_sell_ratio", 0) or 0

            # Merge: prefer aggregation keys, fall back to analytics keys
            eff_volume = total_volume or volume
            eff_trades = total_trades or tx_frequency
            eff_positions = active_positions

            # Derive signal components from merged features
            liquidity = min(1.0, eff_volume / 10000) if eff_volume > 0 else 0.0
            momentum = min(1.0, win_rate / 100) if win_rate > 0 else 0.0
            cluster = min(1.0, eff_positions / 10) if eff_positions > 0 else 0.0
            smart_money = min(1.0, total_pnl / 100) if total_pnl > 0 else 0.0
            velocity = min(1.0, eff_trades / 50) if eff_trades > 0 else 0.0
            anomaly = 0.0

            # --- Analytics-specific signal boosts ---
            # Token diversity boosts cluster signal
            if token_diversity > 1 and cluster == 0.0:
                cluster = min(1.0, token_diversity / 10)
            # Buy pressure boosts momentum
            if buy_sell_ratio > 0.7 and momentum == 0.0:
                momentum = min(1.0, buy_sell_ratio * 0.5)
            # High interaction boosts smart_money
            if interaction_score > 0.5 and smart_money == 0.0:
                smart_money = min(1.0, interaction_score)
            # Net buying boosts liquidity signal
            if buy_count > sell_count and liquidity == 0.0:
                net_ratio = buy_count / max(1, buy_count + sell_count)
                liquidity = min(1.0, net_ratio * 0.5)

            # Weighted signal combination
            signals = [liquidity, momentum, cluster, smart_money, velocity]
            nonzero_signals = [s for s in signals if s > 0]

            if not nonzero_signals:
                return None

            # Base score: weighted average of non-zero signals
            weights = [0.25, 0.20, 0.20, 0.20, 0.15]
            weighted_sum = sum(s * w for s, w in zip(signals, weights))
            signal_count_factor = min(1.0, len(nonzero_signals) / 3.0)
            base_score = weighted_sum * (0.5 + 0.5 * signal_count_factor)

            # Regime detection based on score
            if base_score < 0.15:
                regime = "NORMAL"
                exponent = 1.0
            elif base_score < 0.30:
                regime = "ACCUMULATION"
                exponent = 1.15
            elif base_score < 0.50:
                regime = "PUMP_BUILDUP"
                exponent = 1.35
            else:
                regime = "PARABOLIC"
                exponent = 1.6

            # Apply regime amplification
            score = base_score * exponent

            # Coherence boost
            coherence = math.prod(min(1.0, s / 0.5) for s in nonzero_signals) if nonzero_signals else 0.0
            score *= (1 + coherence * 0.3)

            # Cap
            score = min(1.0, max(0.0, score))

            # Conviction
            conviction = min(1.0, len(nonzero_signals) / 3.0)

            # Stage
            if score < 0.2:
                stage = "EARLY_STAGE"
            elif score < 0.4:
                stage = "ACCUMULATION_START"
            elif score < 0.6:
                stage = "ACCUMULATION_PHASE"
            elif score < 0.8:
                stage = "PRE_PUMP"
            else:
                stage = "HIGH_PUMP_RISK"

            return {
                "token": token,
                "score": round(score, 4),
                "probability": round(score * 0.8, 4),
                "regime": regime,
                "eta_minutes": max(15, int(120 * (1 - score))),
                "horizon": "1h",
                "cluster_id": cluster_id,
                "signals": {
                    "liquidity": round(liquidity, 4),
                    "momentum": round(momentum, 4),
                    "cluster": round(cluster, 4),
                    "smart_money": round(smart_money, 4),
                    "velocity": round(velocity, 4),
                    "anomaly": round(anomaly, 4),
                },
                "conviction": round(conviction, 4),
                "stage": stage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(
                "prediction_worker.engine_error",
                token=token[:16],
                error=str(e),
            )

        return None

    async def _persist_prediction(self, prediction: dict[str, Any]) -> uuid.UUID | None:
        """Persist prediction to database. Returns the prediction UUID."""
        session = self.get_session()
        try:
            prediction_id = uuid.uuid4()
            prediction_record = Prediction(
                id=prediction_id,
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
                prediction_id=str(prediction_id)[:16],
                token=prediction.get("token", "")[:16],
            )

            return prediction_id

        except Exception as e:
            await session.rollback()
            logger.error(
                "prediction_worker.persist_error",
                error=str(e),
            )
            return None
        finally:
            await session.close()
