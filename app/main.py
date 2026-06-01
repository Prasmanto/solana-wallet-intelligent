"""Application bootstrap.

Creates and configures the FastAPI application with:
- Structured logging
- Lifespan-managed resources (DB, Redis)
- CORS middleware
- API versioned routing
- Health check endpoints
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.logging import setup_logging
from app.config.settings import settings
from app.infrastructure.database.manager import DatabaseManager
from app.infrastructure.redis.manager import RedisManager

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown lifecycle.

    Startup order: logging → database → redis → workers
    Shutdown order: workers → redis → database
    """
    # ── Startup ─────────────────────────────────────────────

    # 1. Logging
    json_output = settings.APP_ENV == "production"
    setup_logging(log_level=settings.LOG_LEVEL, json_output=json_output)
    logger.info(
        "app.starting",
        env=settings.APP_ENV,
        role=settings.SERVICE_ROLE,
        debug=settings.DEBUG,
    )

    # 2. Database
    db_manager = DatabaseManager(settings)
    await db_manager.connect()
    app.state.db_manager = db_manager

    # 3. Redis
    redis_manager = RedisManager(settings)
    await redis_manager.connect()
    app.state.redis_manager = redis_manager

    logger.info("app.ready", env=settings.APP_ENV)

    yield

    # ── Shutdown ────────────────────────────────────────────
    logger.info("app.shutting_down")

    await redis_manager.close()
    await db_manager.close()

    logger.info("app.stopped")


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Solana Wallet Intelligence Platform",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Store settings on app for access in middleware
    app.state.settings = settings

    # ── Middleware ───────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID middleware (adds X-Request-ID header)
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Response:
        import uuid

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Routes ──────────────────────────────────────────────
    from app.api.router import api_router
    from app.config.metrics import get_metrics
    from fastapi.responses import PlainTextResponse

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Metrics endpoint (Prometheus)
    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return get_metrics().decode("utf-8")

    # ── Exception Handlers ──────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()
