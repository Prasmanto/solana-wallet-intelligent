"""Alert worker — evaluates rules and dispatches notifications.

Pipeline position: trade.enriched → alert.triggered

Production guarantees:
- Idempotent: event_id checked before processing
- ACK only after DB commit
- Crash recovery via XAUTOCLAIM
"""

from __future__ import annotations

import structlog

from app.core.domain.events import EventEnvelope
from app.core.domain.stream_names import StreamName
from app.workers.base import ConsumerWorker

logger = structlog.get_logger(__name__)


class AlertWorker(ConsumerWorker):
    """Consumes enriched trades and evaluates alert rules."""

    stream = StreamName.TRADE_ENRICHED
    group = "alert"
    concurrency = 2
    block_ms = 5000

    async def process(self, envelope: EventEnvelope) -> None:
        """Evaluate alert rules against the trade.

        Must commit to DB before returning.
        """
        logger.info(
            "alert_worker.processing",
            event_id=envelope.event_id[:16],
            event_type=envelope.event_type,
            stage="process",
        )

        payload = envelope.payload_dict

        # 1. Evaluate basic alert rules
        alerts_triggered = await self._evaluate_alerts(payload)

        # 2. If any alerts triggered, publish to ALERT_TRIGGERED
        if alerts_triggered:
            for alert in alerts_triggered:
                await self._producer.publish_chain(
                    stream=StreamName.ALERT_TRIGGERED,
                    event_type="alert.triggered",
                    payload={
                        **payload,
                        "alert": alert,
                    },
                    source_envelope=envelope,
                    metadata={
                        "stage": "alert",
                        "worker": "alert_worker",
                        "alert_type": alert["type"],
                    },
                )

            logger.info(
                "alert_worker.alerts_triggered",
                event_id=envelope.event_id[:16],
                alert_count=len(alerts_triggered),
                wallet=payload.get("wallet", "")[:16] if payload.get("wallet") else "",
                stage="completed",
            )
        else:
            logger.info(
                "alert_worker.no_alerts",
                event_id=envelope.event_id[:16],
                wallet=payload.get("wallet", "")[:16] if payload.get("wallet") else "",
                stage="completed",
            )

    async def _evaluate_alerts(self, payload: dict) -> list[dict]:
        """Evaluate alert rules against the trade.

        Currently implements basic rules:
        1. Large trade detection (amount > threshold)
        2. High confidence trade detection
        3. Smart money detection

        Returns list of triggered alerts.
        """
        alerts = []

        wallet = payload.get("wallet", "")
        event_type = payload.get("event_type", "")
        amount = payload.get("amount", 0)
        confidence = payload.get("confidence", 0)

        # Rule 1: Large trade detection
        LARGE_TRADE_THRESHOLD = 1000  # tokens
        if amount > LARGE_TRADE_THRESHOLD:
            alerts.append({
                "type": "large_trade",
                "severity": "medium",
                "message": f"Large {event_type} detected: {amount:,.2f} tokens",
                "threshold": LARGE_TRADE_THRESHOLD,
                "actual": amount,
            })

        # Rule 2: High confidence trade
        HIGH_CONFIDENCE_THRESHOLD = 0.8
        if confidence > HIGH_CONFIDENCE_THRESHOLD:
            alerts.append({
                "type": "high_confidence_trade",
                "severity": "low",
                "message": f"High confidence {event_type} detected",
                "threshold": HIGH_CONFIDENCE_THRESHOLD,
                "actual": confidence,
            })

        # Rule 3: Smart money detection (placeholder)
        intelligence = payload.get("intelligence", {})
        smart_money = intelligence.get("smart_money")
        if smart_money and smart_money.get("is_smart_money", False):
            alerts.append({
                "type": "smart_money_detected",
                "severity": "high",
                "message": "Smart money activity detected",
                "details": smart_money,
            })

        return alerts
