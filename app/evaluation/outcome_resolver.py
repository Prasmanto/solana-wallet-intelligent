"""Outcome resolver — evaluates predictions after time horizon."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.evaluation_models import PredictionRecord, PredictionOutcome

logger = structlog.get_logger(__name__)


class OutcomeResolver:
    """Resolves prediction outcomes after time horizon."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_pending(self) -> int:
        """Resolve all pending predictions that have passed their horizon.

        Returns number of predictions resolved.
        """
        # Get pending predictions
        stmt = (
            select(Prediction)
            .where(Prediction.status == "PENDING")
            .order_by(Prediction.created_at.asc())
        )
        result = await self._session.execute(stmt)
        predictions = result.scalars().all()

        resolved_count = 0
        for pred in predictions:
            outcome = self._evaluate_prediction(pred)
            if outcome:
                await self._store_outcome(pred.id, outcome)
                await self._mark_resolved(pred.id)
                resolved_count += 1

        logger.info("resolver.batch_resolved", count=resolved_count)
        return resolved_count

    def _evaluate_prediction(self, pred: Any) -> dict[str, Any] | None:
        """Evaluate if prediction should be resolved."""
        created_at = pred.created_at
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        horizon_minutes = pred.prediction_horizon
        if horizon_minutes == "15m":
            horizon = 15
        elif horizon_minutes == "1h":
            horizon = 60
        elif horizon_minutes == "4h":
            horizon = 240
        else:
            horizon = 60

        # Check if enough time has passed
        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
        if elapsed < horizon:
            return None  # Not ready yet

        # Evaluate outcome (simplified - in production would check price data)
        success = self._determine_success(pred)

        return {
            "prediction_id": str(pred.id),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "actual_return_15m": 0.0,
            "actual_return_1h": 0.0,
            "actual_return_4h": 0.0,
            "volume_change": 0.0,
            "success": success,
            "outcome_score": 1.0 if success else 0.0,
            "resolution_reason": "horizon_elapsed",
        }

    def _determine_success(self, pred: Any) -> bool:
        """Determine if prediction was successful.

        In production, would check actual price data.
        Simplified: use confidence as proxy for now.
        """
        # Higher confidence predictions have higher chance of success
        confidence = pred.predicted_probability
        # Simulate success based on confidence
        return float(confidence) > 0.5

    async def _store_outcome(self, prediction_id: str, outcome: dict[str, Any]) -> None:
        """Store prediction outcome."""
        stmt = (
            sa_insert(PredictionOutcome)
            .values(
                id=uuid.uuid4(),
                prediction_id=prediction_id,
                resolved_at=outcome["resolved_at"],
                actual_return_15m=outcome.get("actual_return_15m", 0),
                actual_return_1h=outcome.get("actual_return_1h", 0),
                actual_return_4h=outcome.get("actual_return_4h", 0),
                volume_change=outcome.get("volume_change", 0),
                success=outcome.get("success", False),
                outcome_score=outcome.get("outcome_score", 0),
                resolution_reason=outcome.get("resolution_reason", ""),
            )
        )
        await self._session.execute(stmt)

    async def _mark_resolved(self, prediction_id: str) -> None:
        """Mark prediction as resolved."""
        stmt = (
            sa_update(Prediction)
            .where(Prediction.id == uuid.UUID(prediction_id))
            .values(status="RESOLVED")
        )
        await self._session.execute(stmt)

    async def get_recent_outcomes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent resolved predictions with outcomes."""
        stmt = (
            select(Prediction, PredictionOutcome)
            .join(PredictionOutcome, Prediction.id == PredictionOutcome.prediction_id)
            .order_by(PredictionOutcome.resolved_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)

        outcomes = []
        for pred, outcome in result:
            outcomes.append({
                "prediction": {
                    "id": str(pred.id),
                    "type": pred.prediction_type,
                    "token": pred.token,
                    "score": pred.predicted_score,
                    "probability": pred.predicted_probability,
                    "horizon": pred.prediction_horizon,
                },
                "outcome": {
                    "success": outcome.success,
                    "outcome_score": outcome.outcome_score,
                    "resolved_at": outcome.resolved_at,
                },
            })

        return outcomes


# Import SQLAlchemy helpers
from sqlalchemy import insert as sa_insert, update as sa_update
