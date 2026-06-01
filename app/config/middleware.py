"""Middleware — HTTP metrics, tracing, and request context.

Provides:
- Request ID middleware (existing)
- Metrics collection middleware
- Correlation ID middleware
- Shadow mode middleware
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
from app.config.tracing import set_correlation_id, set_request_id

logger = structlog.get_logger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP request metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        response = await call_next(request)

        # Track duration
        duration = time.time() - start_time
        endpoint = request.url.path
        method = request.method
        status = str(response.status_code)

        HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status).inc()

        return response


class TracingMiddleware(BaseHTTPMiddleware):
    """Middleware to propagate trace context."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        set_request_id(request_id)

        # Get or generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        set_correlation_id(correlation_id)

        response = await call_next(request)

        # Add trace headers to response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response


class ShadowModeMiddleware(BaseHTTPMiddleware):
    """Middleware for shadow mode deployment."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from app.config.health import shadow_mode

        # Add shadow mode header
        response = await call_next(request)

        if shadow_mode.enabled:
            response.headers["X-Shadow-Mode"] = "true"
            if shadow_mode.metrics_only:
                response.headers["X-Shadow-Mode"] = "metrics-only"

        return response
