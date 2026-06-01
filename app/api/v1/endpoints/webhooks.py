"""Helius webhook endpoint.

FastAPI endpoint for receiving Helius Enhanced Webhook payloads.

Pipeline:
1. Receive raw request body
2. Validate webhook signature (X-Helius-Signature)
3. Parse JSON payload
4. Ingest transactions (persist + publish)
5. Return acknowledgment

Design:
- Returns 200 OK immediately after successful ingestion
- Returns 422 for invalid payloads (Helius will retry)
- Returns 401 for invalid signatures
- Returns 500 for internal errors (Helius will retry)
"""

from __future__ import annotations

import asyncio
import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_streams
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.infrastructure.redis.producer import EventProducer
from app.infrastructure.redis.streams import StreamsManager
from app.schemas.helius import (
    HeliusWebhookPayload,
    WebhookIngestionResult,
    WebhookTransaction,
)
from app.services.ingestion_service import IngestionService

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_ingestion_service(
    db: AsyncSession,
    redis_streams,
) -> IngestionService:
    """Create ingestion service with dependencies."""
    repo = RawEventRepository(db)
    streams_manager = StreamsManager(redis_streams)
    producer = EventProducer(streams_manager)
    return IngestionService(repo=repo, producer=producer)


@router.post(
    "/helius",
    summary="Helius Enhanced Webhook",
    response_model=WebhookIngestionResult,
    status_code=status.HTTP_200_OK,
)
async def helius_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_streams=Depends(get_redis_streams),
) -> WebhookIngestionResult:
    """Receive and process Helius Enhanced Webhook."""
    # 1. Read raw body with timeout protection
    try:
        body = await asyncio.wait_for(request.body(), timeout=5.0)
    except asyncio.TimeoutError:
        return Response(
            content='{"error": "Request body timeout"}',
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            media_type="application/json",
        )
    except Exception:
        return Response(
            content='{"error": "Failed to read request body"}',
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="application/json",
        )

    # 2. Validate webhook signature
    signature_header = request.headers.get("X-Helius-Signature")
    service = _get_ingestion_service(db, redis_streams)

    validation = service.validate_webhook(body, signature_header)
    if not validation.valid:
        logger.warning(
            "webhook.validation_failed",
            error=validation.error,
        )
        return Response(
            content=f'{{"error": "{validation.error}"}}',
            status_code=status.HTTP_401_UNAUTHORIZED,
            media_type="application/json",
        )

    # 3. Parse JSON payload
    try:
        payload_json = await request.json()

        # Helius often sends raw array payloads
        if isinstance(payload_json, list):
            payload = HeliusWebhookPayload(
                transactions=[
                    WebhookTransaction.model_validate(tx)
                    for tx in payload_json
                ]
            )
        else:
            payload = HeliusWebhookPayload.model_validate(payload_json)

    except Exception as e:
        logger.warning(
            "webhook.parse_error",
            error=str(e),
        )
        return Response(
            content=f'{{"error": "Invalid JSON payload: {str(e)}"}}',
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            media_type="application/json",
        )

    # 4. Ingest transactions
    try:
        result = await service.ingest_webhook(payload)
    except Exception as e:
        logger.error(
            "webhook.ingestion_failed",
            error=str(e),
            exc_info=True,
        )
        return Response(
            content=f'{{"error": "Internal error: {str(e)}"}}',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json",
        )

    # 5. Return result
    return result


@router.post(
    "/helius/test",
    summary="Test webhook endpoint",
    status_code=status.HTTP_200_OK,
)
async def helius_webhook_test() -> dict:
    """Test endpoint for verifying webhook connectivity.

    Helius sends a test payload to verify the endpoint is reachable.
    """
    logger.info("webhook.test_received")
    return {"status": "ok", "message": "Webhook endpoint is reachable"}
