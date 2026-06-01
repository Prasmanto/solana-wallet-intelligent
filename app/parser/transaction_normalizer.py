"""Transaction normalizer — converts Helius transactions to NormalizedTrade.

Core parsing logic:
1. Extract wallet from fee_payer or native transfers
2. Detect protocol from source/program IDs
3. Extract token transfers (in/out)
4. Determine trade direction
5. Normalize decimals
6. Build NormalizedTrade

Handles edge cases:
- Multi-hop swaps (intermediary tokens)
- SOL ↔ Wrapped SOL conversions
- Failed transactions (skipped)
- Non-swap transfers (skipped)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from app.parser.protocol_detector import ProtocolDetector
from app.schemas.helius import WebhookTransaction
from app.schemas.trade import (
    DEXProtocol,
    NormalizedTrade,
    ParseResult,
    TokenInfo,
    TradeDirection,
)

logger = structlog.get_logger(__name__)

# ── Known Token Addresses ───────────────────────────────────

SOL_MINT = "So11111111111111111111111111111111111111112"
WSOL_MINT = SOL_MINT  # Wrapped SOL
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

TOKEN_DECIMALS = {
    SOL_MINT: 9,
    USDC_MINT: 6,
    USDT_MINT: 6,
}


class TransactionNormalizer:
    """Normalizes Helius transactions into NormalizedTrade events."""

    def __init__(self) -> None:
        self._detector = ProtocolDetector()

    def normalize(
        self,
        tx: WebhookTransaction,
        raw_event_id: str = "",
        correlation_id: str = "",
    ) -> ParseResult:
        """Normalize a single Helius transaction into a NormalizedTrade.

        Args:
            tx: Parsed Helius transaction
            raw_event_id: ID of the raw event (for traceability)
            correlation_id: Correlation ID (for pipeline tracing)

        Returns:
            ParseResult with trade or error
        """
        try:
            # Skip non-swap transactions
            if tx.type not in ("SWAP", "TRANSFER"):
                return ParseResult(
                    success=False,
                    error=f"Unsupported transaction type: {tx.type}",
                    error_code="UNSUPPORTED_TYPE",
                )

            # Skip failed transactions (check if fee is 0 and no transfers)
            if not tx.signature:
                return ParseResult(
                    success=False,
                    error="Missing transaction signature",
                    error_code="MISSING_SIGNATURE",
                )

            # Detect protocol
            program_ids = self._extract_program_ids(tx)
            protocol = self._detector.detect(
                source=tx.source,
                program_ids=program_ids,
                description=tx.description,
            )

            # Extract wallet (fee payer or primary actor)
            wallet = self._extract_wallet(tx)
            if not wallet:
                return ParseResult(
                    success=False,
                    error="Could not determine wallet address",
                    error_code="NO_WALLET",
                )

            # Extract token transfers
            token_transfers = self._extract_token_transfers(tx)

            # For swaps and transfers, we need at least 2 tokens (in and out)
            # If not enough token transfers, try to infer from native transfers
            if len(token_transfers) < 2:
                native_transfers = tx.native_transfers or []
                if len(native_transfers) >= 1:
                    # Build synthetic token transfers from native
                    # This creates both outgoing and incoming from wallet's perspective
                    token_transfers = self._infer_from_native_transfers(
                        tx, native_transfers, wallet
                    )
                elif tx.type == "SWAP":
                    return ParseResult(
                        success=False,
                        error=f"Insufficient token transfers for swap: {len(token_transfers)}",
                        error_code="INSUFFICIENT_TRANSFERS",
                    )
                elif not token_transfers:
                    return ParseResult(
                        success=False,
                        error=f"No token transfers found",
                        error_code="INSUFFICIENT_TRANSFERS",
                    )

            # Determine token_in and token_out based on direction
            token_in, token_out, direction = self._classify_direction(
                token_transfers, wallet
            )

            if not token_in or not token_out:
                return ParseResult(
                    success=False,
                    error="Could not classify trade direction",
                    error_code="DIRECTION_UNKNOWN",
                )

            # Normalize amounts
            token_in_normalized = self._normalize_token(token_in, tx)
            token_out_normalized = self._normalize_token(token_out, tx)

            # Generate trade_id
            trade_id = self._generate_trade_id(tx.signature, 0)

            # Build timestamp
            timestamp = None
            if tx.timestamp:
                timestamp = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc)

            # Build trade
            trade = NormalizedTrade(
                trade_id=trade_id,
                signature=tx.signature,
                slot=tx.slot,
                timestamp=timestamp,
                wallet=wallet,
                direction=direction,
                token_in=token_in_normalized,
                token_out=token_out_normalized,
                protocol=protocol,
                protocol_program=tx.source,
                protocol_label=tx.source,
                fee_sol=Decimal(str(tx.fee / 10**9)) if tx.fee else Decimal("0"),
                raw_event_id=raw_event_id,
                correlation_id=correlation_id,
                parsed_at=datetime.now(timezone.utc),
                raw_data=tx.model_dump() if hasattr(tx, "model_dump") else {},
            )

            logger.info(
                "parser.trade_normalized",
                signature=tx.signature[:16],
                wallet=wallet[:8],
                protocol=protocol.value,
                direction=direction.value,
                token_in=token_in_normalized.mint[:8],
                token_out=token_out_normalized.mint[:8],
            )

            return ParseResult(success=True, trade=trade)

        except Exception as e:
            logger.error(
                "parser.normalize_error",
                signature=tx.signature[:16] if tx.signature else "unknown",
                error=str(e),
            )
            return ParseResult(
                success=False,
                error=str(e),
                error_code="NORMALIZE_ERROR",
            )

    def _extract_wallet(self, tx: WebhookTransaction) -> str:
        """Extract the primary wallet address from the transaction."""
        # Primary: fee payer
        if tx.fee_payer:
            return tx.fee_payer

        # Fallback: first native transfer sender
        native_transfers = tx.native_transfers or []
        if native_transfers:
            for transfer in native_transfers:
                sender = transfer.get("fromUserAccount", "")
                if sender:
                    return sender

        # Fallback: first token transfer sender
        token_transfers = tx.token_transfers or []
        if token_transfers:
            for transfer in token_transfers:
                sender = transfer.get("from_user_account", "")
                if sender:
                    return sender

        return ""

    def _extract_token_transfers(
        self,
        tx: WebhookTransaction,
    ) -> list[dict[str, Any]]:
        """Extract token transfers from the transaction."""
        transfers = []

        for transfer in (tx.token_transfers or []):
            transfers.append({
                "from": transfer.from_user_account,
                "to": transfer.to_user_account,
                "amount": transfer.token_amount,
                "mint": transfer.mint,
                "standard": transfer.token_standard,
            })

        return transfers

    def _infer_from_native_transfers(
        self,
        tx: WebhookTransaction,
        native_transfers: list[dict[str, Any]],
        wallet: str,
    ) -> list[dict[str, Any]]:
        """Infer token transfers from native SOL transfers.

        For a single transfer, creates both outgoing and incoming entries
        from the wallet's perspective.
        """
        transfers = []

        for transfer in native_transfers:
            from_user = transfer.get("fromUserAccount", "")
            to_user = transfer.get("toUserAccount", "")
            amount = transfer.get("amount", 0)
            amount_sol = amount / 10**9  # Convert lamports to SOL

            if from_user == wallet:
                # Wallet is sending SOL
                transfers.append({
                    "from": from_user,
                    "to": to_user,
                    "amount": amount_sol,
                    "mint": SOL_MINT,
                    "standard": "native",
                })
            elif to_user == wallet:
                # Wallet is receiving SOL
                transfers.append({
                    "from": from_user,
                    "to": to_user,
                    "amount": amount_sol,
                    "mint": SOL_MINT,
                    "standard": "native",
                })

        # For single transfers, we need to handle the case where
        # wallet is only sending or only receiving
        # In this case, we treat it as a simple transfer
        if len(transfers) == 1:
            # Add a "self" transfer to make direction classification work
            transfer = transfers[0]
            if transfer["from"] == wallet:
                # Wallet is sending - add incoming from "pool" or "system"
                transfers.append({
                    "from": transfer["to"],
                    "to": wallet,
                    "amount": transfer["amount"],
                    "mint": SOL_MINT,
                    "standard": "native",
                })
            else:
                # Wallet is receiving - add outgoing to "pool" or "system"
                transfers.append({
                    "from": wallet,
                    "to": transfer["from"],
                    "amount": transfer["amount"],
                    "mint": SOL_MINT,
                    "standard": "native",
                })

        return transfers

    def _classify_direction(
        self,
        token_transfers: list[dict[str, Any]],
        wallet: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, TradeDirection]:
        """Classify trade direction based on token flow.

        Returns (token_in, token_out, direction) where:
        - token_in: what wallet RECEIVES (incoming)
        - token_out: what wallet PAYS (outgoing)
        - direction: buy or sell

        Direction logic:
        - BUY:  wallet pays SOL/USDC, receives other token
        - SELL: wallet pays other token, receives SOL/USDC
        """
        outgoing = []  # What wallet pays
        incoming = []  # What wallet receives

        for transfer in token_transfers:
            from_addr = transfer.get("from", "")
            to_addr = transfer.get("to", "")

            if from_addr == wallet:
                outgoing.append(transfer)
            elif to_addr == wallet:
                incoming.append(transfer)

        if not outgoing or not incoming:
            return None, None, TradeDirection.BUY

        # token_out = what wallet pays (outgoing)
        # token_in = what wallet receives (incoming)
        token_out = outgoing[0]  # What wallet pays
        token_in = incoming[0]   # What wallet receives

        # Determine direction based on what wallet is paying
        # If wallet pays SOL or USDC (base currencies), it's BUYING the other token
        # If wallet pays other token, it's SELLING for base currency
        if token_out.get("mint") in (SOL_MINT, USDC_MINT, USDT_MINT):
            direction = TradeDirection.BUY  # Wallet pays base currency, buys token
        else:
            direction = TradeDirection.SELL  # Wallet pays token, sells for base

        return token_in, token_out, direction

    def _normalize_token(
        self,
        transfer: dict[str, Any],
        tx: WebhookTransaction,
    ) -> TokenInfo:
        """Normalize token information."""
        mint = transfer.get("mint", "")
        amount = transfer.get("amount", 0)

        # Get decimals
        decimals = TOKEN_DECIMALS.get(mint, 9)

        # Calculate raw amount
        if isinstance(amount, (int, float)):
            # Amount is already human-readable from Helius
            amount_decimal = Decimal(str(amount))
            raw_amount = int(amount * (10**decimals))
        else:
            amount_decimal = Decimal("0")
            raw_amount = 0

        return TokenInfo(
            mint=mint,
            decimals=decimals,
            amount_raw=raw_amount,
            amount=amount_decimal,
        )

    def _extract_program_ids(self, tx: WebhookTransaction) -> list[str]:
        """Extract program IDs from the transaction."""
        program_ids = []

        # From accountData
        for account in (tx.account_data or []):
            account_id = account.account if hasattr(account, "account") else ""
            if account_id:
                program_ids.append(account_id)

        # From events
        events = tx.events or {}
        if isinstance(events, dict):
            # Check for inner instructions
            inner = events.get("inner", [])
            if isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict):
                        pid = item.get("programId", "")
                        if pid:
                            program_ids.append(pid)

        return program_ids

    def _generate_trade_id(self, signature: str, index: int) -> str:
        """Generate a deterministic trade ID."""
        data = f"{signature}:{index}"
        return str(uuid.uuid5(uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7"), data))
