"""Metrics engine — computes evaluation metrics and accuracy."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.evaluation_models import EvaluationMetrics

logger = structlog.get_logger(__name__)


class MetricsEngine:
    """Computes evaluation metrics and accuracy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compute_metrics(self) -> EvaluationMetrics:
        """Compute all evaluation metrics."""
        # Overall accuracy
        total = await self._count_predictions()
        resolved = await self._count_resolved()
        successful = await self._count_successful()

        overall_accuracy = successful / max(resolved, 1)

        # Accuracy by horizon
        accuracy_15m = await self._compute_accuracy_by_horizon("15m")
        accuracy_1h = await self._compute_accuracy_by_horizon("1h")
        accuracy_4h = await self._compute_accuracy_by_horizon("4h")

        # Precision and recall
        precision = await self._compute_precision()
        recall = await self._compute_recall()
        win_rate = await self._compute_win_rate()

        # Average return
        avg_return = await self._compute_average_return()

        # Confidence calibration
        calibration = await self._compute_confidence_calibration()

        return EvaluationMetrics(
            overall_accuracy=overall_accuracy,
            accuracy_15m=accuracy_15m,
            accuracy_1h=accuracy_1h,
            accuracy_4h=accuracy_4h,
            total_predictions=total,
            resolved_predictions=resolved,
            precision=precision,
            recall=recall,
            win_rate=win_rate,
            average_return=avg_return,
            confidence_calibration=calibration,
        )

    async def _count_predictions(self) -> int:
        """Count total predictions."""
        stmt = select(func.count(Prediction.id))
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _count_resolved(self) -> int:
        """Count resolved predictions."""
        stmt = select(func.count(Prediction.id)).where(
            Prediction.status == "RESOLVED"
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _count_successful(self) -> int:
        """Count successful predictions."""
        stmt = (
            select(func.count(PredictionOutcome.id))
            .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
            .where(PredictionOutcome.success == True)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _compute_accuracy_by_horizon(self, horizon: str) -> float:
        """Compute accuracy for a specific horizon."""
        stmt = (
            select(func.count(PredictionOutcome.id))
            .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
            .where(
                and_(
                    Prediction.prediction_horizon == horizon,
                    Prediction.status == "RESOLVED",
                    PredictionOutcome.success == True,
                )
            )
        )
        result = await self._session.execute(stmt)
        successful = result.scalar() or 0

        total_stmt = (
            select(func.count(Prediction.id))
            .where(
                and_(
                    Prediction.prediction_horizon == horizon,
                    Prediction.status == "RESOLVED",
                )
            )
        )
        result = await self._session.execute(total_stmt)
        total = result.scalar() or 0

        return successful / max(total, 1)

    async def _compute_precision(self) -> float:
        """Compute precision (successful / total predictions)."""
        total = await self._count_predictions()
        successful = await self._count_successful()
        return successful / max(total, 1)

    async def _compute_recall(self) -> float:
        """Compute recall (resolved / total predictions)."""
        total = await self._count_predictions()
        resolved = await self._count_resolved()
        return resolved / max(total, 1)

    async def _compute_win_rate(self) -> float:
        """Compute win rate (successful / resolved)."""
        resolved = await self._count_resolved()
        successful = await self._count_successful()
        return successful / max(resolved, 1)

    async def _compute_average_return(self) -> float:
        """Compute average return across resolved predictions."""
        stmt = (
            select(func.avg(PredictionOutcome.actual_return_1h))
            .where(PredictionOutcome.success == True)
        )
        result = await self._session.execute(stmt)
        avg = result.scalar()
        return float(avg) if avg else 0.0

    async def _compute_confidence_calibration(self) -> dict[str, float]:
        """Compute confidence calibration.

        Returns accuracy for each confidence bracket.
        """
        brackets = [
            (0.0, 0.3, "low"),
            (0.3, 0.5, "medium_low"),
            (0.5, 0.7, "medium"),
            (0.7, 0.8, "medium_high"),
            (0.8, 0.9, "high"),
            (0.9, 1.0, "very_high"),
        ]

        calibration = {}
        for low, high, label in brackets:
            stmt = (
                select(func.count(PredictionOutcome.id))
                .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
                .where(
                    and_(
                        Prediction.predicted_probability >= low,
                        Prediction.predicted_probability < high,
                        Prediction.status == "RESOLVED",
                        PredictionOutcome.success == True,
                    )
                )
            )
            result = await self._session.execute(stmt)
            successful = result.scalar() or 0

            total_stmt = (
                select(func.count(Prediction.id))
                .where(
                    and_(
                        Prediction.predicted_probability >= low,
                        Prediction.predicted_probability < high,
                        Prediction.status == "RESOLVED",
                    )
                )
            )
            result = await self._session.execute(total_stmt)
            total = result.scalar() or 0

            accuracy = successful / max(total, 1)
            calibration[f"{low}-{high}"] = float(accuracy)

        return calibration


# Import SQLAlchemy helpers
from sqlalchemy import insert as sa_insert
