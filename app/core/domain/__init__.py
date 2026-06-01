"""Core domain layer — zero infrastructure dependencies."""

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName

__all__ = ["EventEnvelope", "StreamName"]
