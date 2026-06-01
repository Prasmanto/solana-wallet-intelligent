"""Confidence analysis — analyzes confidence bucket performance."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

CONFIDENCE_BUCKETS = [
    (0.0, 0.3, "low"),
    (0.3, 0.5, "medium_low"),
    (0.5, 0.7, "medium"),
    (0.7, 0.8, "medium_high"),
    (0.8, 0.9, "high"),
    (0.9, 1.0, "very_high"),
]


class ConfidenceAnalysis:
    """Analyze confidence bucket performance."""

    def __init__(self) -> None:
        self._predictions: list[dict[str, Any]] = []

    def record(self, confidence: float, success: bool, actual_return: float) -> None:
        """Record a prediction for confidence analysis."""
        self._predictions.append({
            "confidence": confidence,
            "success": success,
            "actual_return": actual_return,
        })

    def analyze(self) -> dict[str, dict[str, Any]]:
        """Analyze confidence bucket performance."""
        results = {}

        for low, high, label in CONFIDENCE_BUCKETS:
            bucket_preds = [
                p for p in self._predictions
                if low <= p["confidence"] < high
            ]

            if not bucket_preds:
                results[label] = {
                    "range": f"{low:.2f}-{high:.2f}",
                    "count": 0,
                    "success_rate": 0.0,
                    "average_return": 0.0,
                    "calibration_error": 0.0,
                }
                continue

            total = len(bucket_preds)
            successful = sum(1 for p in bucket_preds if p["success"])
            total_return = sum(p["actual_return"] for p in bucket_preds if p["success"])

            success_rate = successful / total
            avg_return = total_return / max(successful, 1)

            # Expected success rate (midpoint of bucket)
            expected_rate = (low + high) / 2
            calibration_error = abs(success_rate - expected_rate)

            results[label] = {
                "range": f"{low:.2f}-{high:.2f}",
                "count": total,
                "success_rate": float(success_rate),
                "average_return": float(avg_return),
                "calibration_error": float(calibration_error),
                "is_overconfident": success_rate < expected_rate - 0.1,
                "is_underconfident": success_rate > expected_rate + 0.1,
            }

        return results

    def get_calibration_quality(self) -> str:
        """Assess overall calibration quality."""
        analysis = self.analyze()

        overconfident_count = sum(
            1 for v in analysis.values()
            if v.get("is_overconfident", False)
        )
        underconfident_count = sum(
            1 for v in analysis.values()
            if v.get("is_underconfident", False)
        )

        if overconfident_count > underconfident_count:
            return "OVERCONFIDENT"
        elif underconfident_count > overconfident_count:
            return "UNDERCONFIDENT"
        else:
            return "WELL_CALIBRATED"
