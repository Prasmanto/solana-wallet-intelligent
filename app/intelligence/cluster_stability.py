"""Cluster stability layer — detects cluster changes and drift.

Monitors:
- Wallet moved clusters
- Cluster drift
- Cluster merge events
- Confidence shifts
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ClusterStabilityMonitor:
    """Monitors cluster stability and detects changes."""

    def __init__(self, repo: Any) -> None:
        self._repo = repo

    async def check_stability(
        self,
        wallet: str,
        old_cluster: str,
        new_cluster: str,
        confidence_shift: float,
    ) -> dict[str, Any] | None:
        """Check if cluster assignment changed and record history.

        Returns change event if significant shift occurred.
        """
        if old_cluster == new_cluster:
            return None

        # Determine reason for change
        reason = self._determine_reason(old_cluster, new_cluster, confidence_shift)

        # Record in history
        change_event = {
            "wallet": wallet,
            "old_cluster": old_cluster,
            "new_cluster": new_cluster,
            "confidence_shift": confidence_shift,
            "reason": reason,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist history
        try:
            await self._repo.record_cluster_history(
                cluster_id=new_cluster,
                wallet_address=wallet,
                event_type="cluster_change",
                old_cluster_id=old_cluster,
                new_cluster_id=new_cluster,
                confidence_shift=confidence_shift,
                reason=reason,
            )
        except Exception as e:
            logger.error(
                "stability.history_error",
                wallet=wallet[:16],
                error=str(e),
                stage="stability",
            )

        logger.info(
            "stability.cluster_change",
            wallet=wallet[:16],
            old_cluster=old_cluster[:16],
            new_cluster=new_cluster[:16],
            confidence_shift=confidence_shift,
            reason=reason,
            stage="stability",
        )

        return change_event

    def _determine_reason(
        self,
        old_cluster: str,
        new_cluster: str,
        confidence_shift: float,
    ) -> str:
        """Determine reason for cluster change."""
        if confidence_shift > 0.3:
            return "significant_confidence_shift"
        elif confidence_shift > 0.1:
            return "moderate_confidence_shift"
        else:
            return "edge_weight_decay_shift"

    async def get_cluster_history(
        self,
        wallet: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get cluster change history for a wallet."""
        return await self._repo.get_cluster_history(wallet, limit)

    async def get_stability_score(self, wallet: str) -> float:
        """Calculate stability score for a wallet.

        Higher score = more stable cluster assignment.
        """
        history = await self.get_cluster_history(wallet, limit=50)

        if not history:
            return 1.0  # No changes = stable

        # Count changes in last hour
        now = datetime.now(timezone.utc)
        recent_changes = sum(
            1 for h in history
            if (now - h["created_at"]).total_seconds() < 3600
        )

        # Score decreases with more recent changes
        if recent_changes == 0:
            return 1.0
        elif recent_changes < 3:
            return 0.8
        elif recent_changes < 10:
            return 0.5
        else:
            return 0.2
