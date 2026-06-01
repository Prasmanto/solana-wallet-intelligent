"""Prediction registry — stores and retrieves predictions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.evaluation_models import PredictionRecord

logger = structlog.get_logger(__name__)


class PredictionRegistry:
    """Stores and retrieves predictions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_prediction(
        self,
        prediction_type: str,
        token: str,
        cluster_id: str,
        predicted_score: float,
        predicted_probability: float,
        predicted_eta_minutes: int,
        prediction_horizon: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register a new prediction. Returns prediction_id."""
        prediction_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        stmt = (
            sa_insert(Prediction)
            .values(
                id=uuid.uuid4(),
                prediction_type=prediction_type,
                token=token,
                cluster_id=cluster_id,
                predicted_score=predicted_score,
                predicted_probability=predicted_probability,
                predicted_eta_minutes=predicted_eta_minutes,
                prediction_horizon=prediction_horizon,
                metadata_json=metadata or {},
                status="PENDING",
                created_at=now,
            )
        )

        await self._session.execute(stmt)
        await self._session.flush()

        logger.info(
            "prediction.registered",
            prediction_id=prediction_id[:16],
            type=prediction_type,
            token=token,
            score=predicted_score,
        )

        return prediction_id

    async def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """Get a prediction by ID."""
        stmt = select(Prediction).where(Prediction.id == uuid.UUID(prediction_id))
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._row_to_dict(row)

    async def get_pending_predictions(
        self,
        prediction_type: str | None = None,
        horizon: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending predictions."""
        conditions = [Prediction.status == "PENDING"]
        if prediction_type:
            conditions.append(Prediction.prediction_type == prediction_type)
        if horizon:
            conditions.append(Prediction.prediction_horizon == horizon)

        stmt = (
            select(Prediction)
            .where(and_(*conditions))
            .order_by(Prediction.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [self._row_to_dict(row) for row in result.scalars().all()]

    async def mark_resolved(self, prediction_id: str) -> None:
        """Mark a prediction as resolved."""
        stmt = (
            sa_update(Prediction)
            .where(Prediction.id == uuid.UUID(prediction_id))
            .values(status="RESOLVED")
        )
        await self._session.execute(stmt)

    async def mark_expired(self, prediction_id: str) -> None:
        """Mark a prediction as expired."""
        stmt = (
            sa_update(Prediction)
            .where(Prediction.id == uuid.UUID(prediction_id))
            .values(status="EXPIRED")
        )
        await self._session.execute(stmt)

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert DB row to dictionary."""
        return {
            "id": str(row.id),
            "prediction_type": row.prediction_type,
            "token": row.token,
            "cluster_id": row.cluster_id,
            "predicted_score": row.predicted_score,
            "predicted_probability": row.predicted_probability,
            "predicted_eta_minutes": row.predicted_eta_minutes,
            "prediction_horizon": row.prediction_horizon,
            "status": row.status,
            "created_at": row.created_at,
            "metadata_json": row.metadata_json or {},
        }


# Import SQLAlchemy helpers
from sqlalchemy import insert as sa_insert, update as sa_update
