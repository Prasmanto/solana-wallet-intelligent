"""Tracing configuration — correlation ID and request tracing.

Provides:
- Correlation ID management
- Request context propagation
- Structured trace context
- Worker trace context

Uses structlog contextvars for trace propagation.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Context Variables ───────────────────────────────────────

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_worker_id: ContextVar[str] = ContextVar("worker_id", default="")
_event_id: ContextVar[str] = ContextVar("event_id", default="")


# ── Correlation ID Management ───────────────────────────────

def get_correlation_id() -> str:
    """Get current correlation ID."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in context."""
    _correlation_id.set(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    cid = str(uuid.uuid4())
    set_correlation_id(cid)
    return cid


def get_request_id() -> str:
    """Get current request ID."""
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    """Set request ID in context."""
    _request_id.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)


def get_worker_id() -> str:
    """Get current worker ID."""
    return _worker_id.get()


def set_worker_id(worker_id: str) -> None:
    """Set worker ID in context."""
    _worker_id.set(worker_id)
    structlog.contextvars.bind_contextvars(worker_id=worker_id)


def get_event_id() -> str:
    """Get current event ID."""
    return _event_id.get()


def set_event_id(event_id: str) -> None:
    """Set event ID in context."""
    _event_id.set(event_id)
    structlog.contextvars.bind_contextvars(event_id=event_id)


# ── Trace Context ───────────────────────────────────────────

def get_trace_context() -> dict[str, str]:
    """Get current trace context as dict."""
    return {
        "correlation_id": get_correlation_id(),
        "request_id": get_request_id(),
        "worker_id": get_worker_id(),
        "event_id": get_event_id(),
    }


def bind_trace_context(
    correlation_id: str | None = None,
    request_id: str | None = None,
    worker_id: str | None = None,
    event_id: str | None = None,
) -> None:
    """Bind trace context to structlog."""
    kwargs: dict[str, str] = {}
    if correlation_id:
        kwargs["correlation_id"] = correlation_id
    if request_id:
        kwargs["request_id"] = request_id
    if worker_id:
        kwargs["worker_id"] = worker_id
    if event_id:
        kwargs["event_id"] = event_id

    if kwargs:
        structlog.contextvars.bind_contextvars(**kwargs)


def clear_trace_context() -> None:
    """Clear all trace context."""
    structlog.contextvars.unbind_contextvars(
        "correlation_id",
        "request_id",
        "worker_id",
        "event_id",
    )
