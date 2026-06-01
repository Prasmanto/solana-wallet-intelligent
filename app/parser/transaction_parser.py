"""Parser module - transforms raw Solana data into structured models.

Responsibilities:
- Decode transaction instructions
- Extract token transfers, swaps, program interactions
- Normalize into Transaction schema
"""

from __future__ import annotations

from typing import Any

import structlog

from app.schemas.transaction import TransactionRead

logger = structlog.get_logger(__name__)


class TransactionParser:
    """Parses raw Solana transaction data into structured records."""

    def parse(self, raw_tx: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a raw transaction into a normalized dict.

        Returns None if the transaction is not relevant to tracked wallets.
        """
        try:
            # Placeholder - implement with solders/borsh deserialization
            parsed = {
                "signature": raw_tx.get("signature", ""),
                "slot": raw_tx.get("slot", 0),
                "block_time": raw_tx.get("block_time"),
                "tx_type": self._classify(raw_tx),
                "program_id": raw_tx.get("program_id"),
                "amount": raw_tx.get("amount"),
                "mint": raw_tx.get("mint"),
                "status": raw_tx.get("status", "success"),
                "raw_data": raw_tx,
            }
            logger.debug("parser.transaction_parsed", signature=parsed["signature"])
            return parsed
        except Exception as e:
            logger.error("parser.parse_error", error=str(e))
            return None

    def _classify(self, raw_tx: dict[str, Any]) -> str:
        """Classify transaction type from instruction data."""
        # Placeholder - classify: swap, transfer, mint, burn, etc.
        return raw_tx.get("type", "unknown")
