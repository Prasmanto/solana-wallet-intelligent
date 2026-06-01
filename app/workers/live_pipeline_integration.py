"""Live pipeline integration — connects predictions to paper trading."""

from __future__ import annotations

import asyncio
import structlog
from typing import Any

from app.workers.paper_trading_worker import PaperTradingWorker

logger = structlog.get_logger(__name__)


class LivePipelineIntegration:
    """Integrates live predictions with paper trading."""

    def __init__(self) -> None:
        self._paper_worker = PaperTradingWorker()
        self._prediction_buffer: list[dict[str, Any]] = []

    async def process_prediction(self, prediction: dict[str, Any]) -> None:
        """Process a live prediction and create virtual position."""
        # Extract prediction data
        token = prediction.get("token", "")
        score = prediction.get("score", 0.0)
        confidence = prediction.get("confidence", 0.0)
        regime = prediction.get("regime", "NORMAL")
        signals = prediction.get("signals_detail", {})
        cluster_id = prediction.get("cluster_id", "")
        smart_money = prediction.get("smart_money_flag", False)

        # Get current price (from prediction or cache)
        current_price = prediction.get("current_price", 0.0)
        if current_price <= 0:
            current_price = self._get_cached_price(token)
            if current_price <= 0:
                logger.warning("pipeline.no_price", token=token)
                return

        # Process through paper trading
        result = await self._paper_worker.process_prediction(
            token=token,
            current_price=current_price,
            prediction_score=score,
            confidence=confidence,
            regime=regime,
            signal_breakdown=signals,
            cluster_id=cluster_id,
            smart_money_present=smart_money,
        )

        if result:
            logger.info(
                "pipeline.position_created",
                token=token,
                position_id=result["position_id"][:16],
                entry_price=result["entry_price"],
            )

    def _get_cached_price(self, token: str) -> float:
        """Get cached price for a token."""
        return self._paper_worker._price_cache.get(token, 0.0)

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update cached prices."""
        self._paper_worker._price_cache.update(prices)

    async def run_worker(self) -> None:
        """Run the paper trading worker."""
        await self._paper_worker.run()
