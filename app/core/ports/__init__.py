"""Core ports — abstract interfaces for infrastructure adapters."""

from abc import ABC, abstractmethod
from typing import Any

from app.core.domain.events import EventEnvelope


class EventBus(ABC):
    """Abstract event bus interface."""

    @abstractmethod
    async def publish(
        self,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """Publish an event to a stream. Returns the stream ID."""
        ...

    @abstractmethod
    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> EventEnvelope | None:
        """Read the next event from a consumer group."""
        ...

    @abstractmethod
    async def ack(self, stream: str, group: str, event_id: str) -> None:
        """Acknowledge an event as processed."""
        ...
