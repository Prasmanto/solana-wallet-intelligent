"""Event enrichment service — classifies and enriches raw events.

Production-safe design:
- Defensive validation of all inputs
- Deterministic classification rules
- Enrichment metadata (confidence, validity, reason)
- Safe defaults for missing fields
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

SOL_MINTS = {
    "So11111111111111111111111111111111111111112",
    "11111111111111111111111111111111",
}

REQUIRED_FIELDS = {"signature", "slot"}


class EnrichmentService:
    """Enriches raw events with classification and validation."""

    def enrich_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Transform a raw event into an enriched event with validation.

        Returns enriched dict with event_type, wallet, token, amount,
        confidence, is_valid, and reason fields.
        """
        signature = event.get("signature", "")
        slot = event.get("slot", 0)
        raw_type = event.get("type", "UNKNOWN")
        data = event.get("data") or {}

        # Validate required fields
        is_valid, reason = self._validate(event)

        if not is_valid:
            return {
                "signature": signature,
                "wallet": "",
                "event_type": "INVALID",
                "token": "",
                "amount": 0,
                "slot": slot,
                "raw_type": raw_type,
                "confidence": 0.0,
                "is_valid": False,
                "reason": reason,
                "source": "heuristic_v1",
            }

        # Classify and extract
        wallet = self._detect_wallet(data)
        event_type, token, amount, confidence = self._classify_event(raw_type, data)

        enriched = {
            "signature": signature,
            "wallet": wallet,
            "event_type": event_type,
            "token": token,
            "amount": amount,
            "slot": slot,
            "raw_type": raw_type,
            "confidence": confidence,
            "is_valid": True,
            "reason": None,
            "source": "heuristic_v1",
        }

        logger.debug(
            "event.enriched",
            signature=signature[:16] if signature else "",
            event_type=event_type,
            confidence=confidence,
        )

        return enriched

    def _validate(self, event: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate event has required fields.

        Returns:
            (is_valid, reason_string or None)
        """
        # Check required fields
        for field in REQUIRED_FIELDS:
            if not event.get(field):
                return False, f"missing_{field}"

        # For SWAP events, data is required
        if event.get("type") == "SWAP":
            data = event.get("data")
            if not data or not isinstance(data, dict):
                return False, "missing_required_fields"

        return True, None

    def _detect_wallet(self, data: dict[str, Any]) -> str:
        """Detect wallet address from event data.

        Priority:
        1. 'from' field (sender wallet)
        2. 'owner' field (account owner)
        3. Empty string (unknown)
        """
        if data.get("from"):
            return str(data["from"])
        if data.get("owner"):
            return str(data["owner"])
        return ""

    def _classify_event(
        self,
        raw_type: str,
        data: dict[str, Any],
    ) -> tuple[str, str, Any, float]:
        """Classify event type and extract token/amount.

        Rules:
        - SWAP with token_in = SOL → BUY
        - SWAP with token_out = SOL → SELL
        - TRANSFER → TRANSFER (if confirmed transfer structure)
        - Other → UNKNOWN

        Returns:
            (event_type, token, amount, confidence)
        """
        if raw_type == "SWAP":
            token_in = str(data.get("token_in", ""))
            token_out = str(data.get("token_out", ""))

            if token_in in SOL_MINTS:
                # Wallet paid SOL, received other token → BUY
                amount = data.get("amount_out", 0)
                has_amount = amount and amount > 0
                confidence = 0.9 if (token_out and has_amount) else 0.5
                return "BUY", token_out, amount, confidence

            elif token_out in SOL_MINTS:
                # Wallet received SOL, paid other token → SELL
                amount = data.get("amount_in", 0)
                has_amount = amount and amount > 0
                confidence = 0.9 if (token_in and has_amount) else 0.5
                return "SELL", token_in, amount, confidence

            else:
                # Non-SOL swap → TRANSFER
                token = token_in or token_out
                amount = data.get("amount", 0)
                has_fields = bool(token) and amount and amount > 0
                confidence = 0.7 if has_fields else 0.3
                return "TRANSFER", token, amount, confidence

        if raw_type == "TRANSFER":
            # Only classify as TRANSFER if transfer-like structure exists
            has_from = bool(data.get("from"))
            has_amount = data.get("amount") and data.get("amount", 0) > 0
            if has_from or has_amount:
                token = data.get("token", "")
                amount = data.get("amount", 0)
                confidence = 0.8 if (has_from and has_amount) else 0.5
                return "TRANSFER", token, amount, confidence
            else:
                return "UNKNOWN", "", 0, 0.2

        # Default: UNKNOWN
        return "UNKNOWN", "", 0, 0.2

    def enrich_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Enrich a batch of events.

        Returns list of enriched events with same order as input.
        """
        return [self.enrich_event(event) for event in events]
