"""Worker orchestrator — lifecycle manager for all async event workers.

Production-grade orchestrator with:
- Structured logging at every stage
- Graceful shutdown with timeout
- Consumer group initialization
- Signal handling (SIGINT, SIGTERM)
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import structlog

from app.config.logging import setup_logging
from app.config.settings import settings
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.redis.manager import RedisManager
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager

logger = structlog.get_logger(__name__)


class WorkerOrchestrator:
    """Manages startup/shutdown of all worker coroutines."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._workers: list[Any] = []
        self._shutdown_event = asyncio.Event()
        self._redis_manager: RedisManager | None = None
        self._db_manager: DatabaseManager | None = None

    async def start(self) -> None:
        """Start all workers."""
        # 1. Logging
        json_output = settings.APP_ENV == "production"
        setup_logging(log_level=settings.LOG_LEVEL, json_output=json_output)

        logger.info("orchestrator.starting", env=settings.APP_ENV, stage="startup")

        # 2. Database
        self._db_manager = DatabaseManager(settings)
        await self._db_manager.connect()
        logger.info("orchestrator.db_ready", stage="startup")

        # 3. Redis
        self._redis_manager = RedisManager(settings)
        await self._redis_manager.connect()

        streams_redis = self._redis_manager.get_client("streams")
        streams_manager = StreamsManager(streams_redis)
        producer = EventProducer(streams_manager)

        # 4. Ensure consumer groups (with retry)
        for attempt in range(3):
            try:
                await streams_manager.ensure_groups()
                logger.info("orchestrator.groups_ready", stage="startup")
                break
            except Exception as e:
                logger.warning("orchestrator.groups_retry", attempt=attempt + 1, error=str(e))
                await asyncio.sleep(2)
        else:
            logger.error("orchestrator.groups_failed", stage="startup")

        # 5. Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # 6. Start workers
        from app.workers.ingestion_worker import IngestionWorker
        from app.workers.parser_worker import ParserWorker
        from app.workers.analytics_worker import AnalyticsWorker
        from app.workers.alert_worker import AlertWorker
        from app.workers.aggregation_worker import AggregationWorker
        from app.workers.prediction_worker import PredictionWorker
        from app.workers.ranking_worker import RankingWorker

        worker_classes = [
            IngestionWorker,
            ParserWorker,
            AnalyticsWorker,
            AggregationWorker,
            AlertWorker,
            PredictionWorker,
            RankingWorker,
        ]

        # Get session factory for workers that need DB access
        session_factory = self._db_manager._session_factory

        # Start stream-based workers
        for cls in worker_classes:
            worker = cls(
                streams=streams_manager,
                producer=producer,
                session_factory=session_factory,
            )
            self._workers.append(worker)
            task = asyncio.create_task(worker.run())
            self._tasks.append(task)

        # Start background workers (not stream-based)
        from app.workers.paper_trading_worker import PaperTradingWorker
        from app.workers.pricing_worker import PricingRefreshWorker
        
        paper_trading_worker = PaperTradingWorker(session_factory=session_factory)
        self._workers.append(paper_trading_worker)
        task = asyncio.create_task(paper_trading_worker.run())
        self._tasks.append(task)

        # Wire PaperTradingWorker to RankingWorker for direct candidate processing
        for w in self._workers:
            if isinstance(w, RankingWorker):
                w._paper_worker = paper_trading_worker
                break
        
        pricing_worker = PricingRefreshWorker()
        self._workers.append(pricing_worker)
        task = asyncio.create_task(pricing_worker.start())
        self._tasks.append(task)

        logger.info("orchestrator.started", workers=len(self._tasks), stage="startup")

        # 7. Block until shutdown
        await self._shutdown_event.wait()
        await self._shutdown()

    def _handle_signal(self) -> None:
        logger.info("orchestrator.signal_received", stage="shutdown")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Graceful shutdown: signal workers → drain → close Redis → close DB."""
        logger.info("orchestrator.shutting_down", stage="shutdown")

        # Signal all workers to stop
        for worker in self._workers:
            await worker.shutdown()

        # Wait for tasks to complete (with timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("orchestrator.shutdown_timeout", stage="shutdown")
            for task in self._tasks:
                if not task.done():
                    task.cancel()

        # Close Redis
        if self._redis_manager:
            await self._redis_manager.close()

        # Close Database
        if self._db_manager:
            await self._db_manager.close()

        logger.info("orchestrator.stopped", stage="shutdown")


async def main() -> None:
    """Entry point for worker process."""
    orchestrator = WorkerOrchestrator()
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
