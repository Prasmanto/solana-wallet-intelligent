"""Ingestion module - consumes raw data from Solana RPC / WebSocket.

Responsibilities:
- Subscribe to Solana event streams
- Forward raw events to parser via Redis pub/sub or Celery tasks
- Handle reconnection and backpressure
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


class SolanaListener:
    """Listens to Solana RPC for wallet-related events."""

    def __init__(self, rpc_url: str, ws_url: str) -> None:
        self.rpc_url = rpc_url
        self.ws_url = ws_url
        self._running = False

    async def start(self) -> None:
        """Start listening for events."""
        self._running = True
        logger.info("solana_listener.started", rpc_url=self.rpc_url)

        while self._running:
            try:
                async for event in self._stream_events():
                    logger.info("solana_listener.event_received", event_type=type(event).__name__)
                    # TODO: dispatch to parser queue
            except Exception as e:
                logger.error("solana_listener.error", error=str(e))
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        logger.info("solana_listener.stopped")

    async def _stream_events(self) -> AsyncIterator[dict]:
        """Yield raw events from Solana WebSocket subscription."""
        # Placeholder - implement with solana-py / solders
        while True:
            await asyncio.sleep(1)
            yield {"type": "placeholder"}
