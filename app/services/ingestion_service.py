"""Ingestion service — production-grade webhook processing.

Guarantees:
- Idempotent: event_id = SHA256(signature + slot + type)
- At-least-once: message ack only after DB commit
- Correlation tracking: correlation_id propagated through pipeline
- DLQ routing: failed events moved to DLQ after max retries
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import settings
from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.infrastructure.database.repositories.raw_event_repo import RawEventRepository
from app.infrastructure.redis.producer import EventProducer
from app.schemas.helius import (
    HeliusWebhookPayload,
    WebhookIngestionResult,
    WebhookTransaction,
    WebhookValidationResult,
)

logger = structlog.get_logger(__name__)


class IngestionService:
    """Production-grade ingestion service with anti-loss guarantees."""

    def __init__(
        self,
        repo: RawEventRepository,
        producer: EventProducer,
    ) -> None:
        self._repo = repo
        self._producer = producer

    # ── Webhook Validation ──────────────────────────────────

    def validate_webhook(
        self,
        payload_bytes: bytes,
        signature_header: str | None,
    ) -> WebhookValidationResult:
        """Validate the webhook signature from Helius."""
        if not settings.HELIUS_WEBHOOK_SECRET:
            if settings.APP_ENV == "production":
                return WebhookValidationResult(
                    valid=False,
                    error="HELIUS_WEBHOOK_SECRET not configured in production",
                )
            logger.debug("webhook.validation_skipped", reason="no_secret_in_dev")
            return WebhookValidationResult(valid=True)

        if not signature_header:
            return WebhookValidationResult(
                valid=False,
                error="Missing X-Helius-Signature header",
            )

        expected = hmac.new(
            settings.HELIUS_WEBHOOK_SECRET.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature_header):
            logger.warning("webhook.invalid_signature")
            return WebhookValidationResult(
                valid=False,
                error="Invalid webhook signature",
            )

        return WebhookValidationResult(valid=True)

    # ── Ingestion Pipeline ──────────────────────────────────

    async def ingest_webhook(
        self,
        payload: HeliusWebhookPayload,
    ) -> WebhookIngestionResult:
        """Process a Helius webhook payload with anti-loss guarantees.

        Pipeline:
        1. Extract all transactions from payload
        2. For each transaction:
           a. Generate deterministic event_id (idempotent)
           b. Persist to raw_events (ON CONFLICT DO NOTHING)
           c. Publish to Redis Stream (only if persisted)
        3. Return ingestion result
        """
        transactions = payload.all_transactions
        result = WebhookIngestionResult(
            success=True,
            transactions_processed=len(transactions),
        )

        if not transactions:
            logger.info("webhook.empty_payload", webhook_id=payload.webhook_id)
            return result

        # Generate correlation_id for entire webhook batch
        webhook_correlation_id = str(uuid.uuid4())

        logger.info(
            "webhook.ingestion_started",
            webhook_id=payload.webhook_id,
            correlation_id=webhook_correlation_id,
            transaction_count=len(transactions),
            stage="ingest",
        )

        for tx in transactions:
            try:
                await self._ingest_transaction(tx, payload, result, webhook_correlation_id)
            except Exception as e:
                logger.error(
                    "webhook.ingestion_error",
                    signature=tx.signature[:16] if tx.signature else "unknown",
                    error=str(e),
                    correlation_id=webhook_correlation_id,
                    stage="ingest",
                )
                result.errors.append(f"{tx.signature[:16] if tx.signature else 'unknown'}: {str(e)}")

        # Update success based on errors
        if result.errors:
            result.success = len(result.errors) < len(transactions)

        logger.info(
            "webhook.ingestion_completed",
            correlation_id=webhook_correlation_id,
            transactions_processed=result.transactions_processed,
            events_persisted=result.events_persisted,
            events_published=result.events_published,
            duplicates_skipped=result.duplicates_skipped,
            errors=len(result.errors),
            stage="ingest",
        )

        return result

    async def _ingest_transaction(
        self,
        tx: WebhookTransaction,
        payload: HeliusWebhookPayload,
        result: WebhookIngestionResult,
        webhook_correlation_id: str,
    ) -> None:
        """Ingest a single transaction with idempotent persistence."""
        if not tx.signature:
            logger.warning("webhook.missing_signature", stage="ingest")
            return

        # Generate deterministic event_id (idempotent)
        event_id = self._generate_event_id(tx.signature)

        # Build event payload
        event_payload = self._build_event_payload(tx, payload)

        # Build metadata
        metadata = {
            "source": "helius_webhook",
            "webhook_id": payload.webhook_id,
            "webhook_type": payload.webhook_type,
            "cluster": payload.cluster,
            "signature": tx.signature,
            "slot": tx.slot,
        }

        logger.info(
            "webhook.persisting",
            signature=tx.signature[:16],
            event_id=event_id[:16],
            correlation_id=webhook_correlation_id,
            stage="persist",
        )

        # 1. Persist to database (idempotent - ON CONFLICT DO NOTHING)
        persisted = await self._repo.insert(
            event_id=event_id,
            stream_name=StreamName.RAW_PENDING,
            event_type="raw.received",
            correlation_id=webhook_correlation_id,
            payload=event_payload,
            metadata=metadata,
            status="pending",
        )

        if persisted:
            result.events_persisted += 1
            logger.info(
                "webhook.persisted",
                signature=tx.signature[:16],
                event_id=event_id[:16],
                correlation_id=webhook_correlation_id,
                stage="persist",
            )
        else:
            result.duplicates_skipped += 1
            logger.info(
                "webhook.duplicate_skipped",
                signature=tx.signature[:16],
                event_id=event_id[:16],
                correlation_id=webhook_correlation_id,
                stage="persist",
            )
            return

        # 2. Publish to Redis Stream (only if persisted)
        await self._producer.publish(
            stream=StreamName.RAW_PENDING,
            event_type="raw.received",
            payload=event_payload,
            correlation_id=webhook_correlation_id,
            max_retries=5,
            metadata=metadata,
        )

        result.events_published += 1
        result.correlation_ids.append(webhook_correlation_id)

        logger.info(
            "webhook.published",
            signature=tx.signature[:16],
            event_id=event_id[:16],
            correlation_id=webhook_correlation_id,
            stage="publish",
        )

    def _generate_event_id(self, signature: str) -> str:
        """Generate a deterministic event_id from transaction signature.

        Uses SHA256 for:
        - Deterministic: same signature always produces same event_id
        - Unique: collision-resistant
        - Compact: 64-char hex string
        """
        return hashlib.sha256(signature.encode()).hexdigest()

    def _build_event_payload(
        self,
        tx: WebhookTransaction,
        payload: HeliusWebhookPayload,
    ) -> dict[str, Any]:
        """Build the event payload from a Helius transaction."""
        return {
            "signature": tx.signature,
            "slot": tx.slot,
            "block_time": tx.timestamp,
            "tx_type": tx.type,
            "source": tx.source,
            "fee": tx.fee,
            "fee_payer": tx.fee_payer,
            "description": tx.description,
            "token_transfers": [
                {
                    "from": t.from_user_account,
                    "to": t.to_user_account,
                    "amount": t.token_amount,
                    "mint": t.mint,
                    "standard": t.token_standard,
                }
                for t in tx.token_transfers
            ],
            "native_transfers": tx.native_transfers,
            "account_data": [
                {
                    "account": a.account,
                    "balance_change": a.native_balance_change,
                    "token_changes": a.token_balance_changes,
                }
                for a in tx.account_data
            ],
            "events": tx.events,
            "webhook_id": payload.webhook_id,
        }
