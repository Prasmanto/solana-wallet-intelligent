"""Normalization validation utilities.

Provides validators for:
- Decimal correctness (precision, range)
- Transfer correctness (wallet involvement, amounts)
- Protocol detection accuracy
- Direction classification
- Deterministic output
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from app.schemas.trade import DEXProtocol, NormalizedTrade, TradeDirection

logger = structlog.get_logger(__name__)

# Known token decimals for validation
KNOWN_DECIMALS = {
    "So11111111111111111111111111111111111111112": 9,  # SOL/WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6,  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6,  # USDT
}


class ValidationResult:
    """Result of a validation check."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        logger.debug("validation.error", message=message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.debug("validation.warning", message=message)

    def __bool__(self) -> bool:
        return self.valid


class TradeValidator:
    """Validates NormalizedTrade output against invariants."""

    def validate(
        self,
        trade: NormalizedTrade,
        expected: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Run all validation checks on a trade."""
        result = ValidationResult()

        # Core field validation
        self._validate_required_fields(trade, result)
        self._validate_decimal_correctness(trade, result)
        self._validate_wallet_involvement(trade, result)
        self._validate_direction(trade, result)
        self._validate_protocol(trade, result)
        self._validate_amounts_positive(trade, result)

        # Expected value comparison (if provided)
        if expected:
            self._validate_against_expected(trade, expected, result)

        return result

    def _validate_required_fields(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate all required fields are present."""
        if not trade.trade_id:
            result.add_error("Missing trade_id")
        if not trade.signature:
            result.add_error("Missing signature")
        if not trade.wallet:
            result.add_error("Missing wallet")
        if not trade.token_in.mint:
            result.add_error("Missing token_in.mint")
        if not trade.token_out.mint:
            result.add_error("Missing token_out.mint")

    def _validate_decimal_correctness(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate decimal amounts are correct."""
        # Check token_in amount
        if trade.token_in.amount < 0:
            result.add_error("token_in.amount is negative")
        if trade.token_in.decimals < 0 or trade.token_in.decimals > 18:
            result.add_error(f"token_in.decimals out of range: {trade.token_in.decimals}")

        # Check token_out amount
        if trade.token_out.amount < 0:
            result.add_error("token_out.amount is negative")
        if trade.token_out.decimals < 0 or trade.token_out.decimals > 18:
            result.add_error(f"token_out.decimals out of range: {trade.token_out.decimals}")

        # Check fee
        if trade.fee_sol < 0:
            result.add_error("fee_sol is negative")

        # Validate against known tokens
        for mint, expected_decimals in KNOWN_DECIMALS.items():
            if trade.token_in.mint == mint and trade.token_in.decimals != expected_decimals:
                result.add_error(
                    f"token_in.decimals mismatch for {mint}: "
                    f"expected {expected_decimals}, got {trade.token_in.decimals}"
                )
            if trade.token_out.mint == mint and trade.token_out.decimals != expected_decimals:
                result.add_error(
                    f"token_out.decimals mismatch for {mint}: "
                    f"expected {expected_decimals}, got {trade.token_out.decimals}"
                )

    def _validate_wallet_involvement(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate wallet is involved in the trade."""
        # Wallet should be different from pool/program addresses
        if len(trade.wallet) < 32:
            result.add_warning("Wallet address appears too short")

        # Check wallet is not a known program
        known_programs = [
            "11111111111111111111111111111111",  # System Program
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
        ]
        if trade.wallet in known_programs:
            result.add_error("Wallet is a system program, not a user wallet")

    def _validate_direction(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate trade direction is consistent."""
        if trade.direction not in (TradeDirection.BUY, TradeDirection.SELL):
            result.add_error(f"Invalid direction: {trade.direction}")

        # Direction should be consistent with token types
        if trade.direction == TradeDirection.BUY:
            # Buying: paying base currency (SOL/USDC), receiving other token
            if trade.token_out.mint not in KNOWN_DECIMALS:
                result.add_warning("BUY direction but paying non-base token")
        else:
            # SELL: paying other token, receiving base currency
            if trade.token_in.mint not in KNOWN_DECIMALS:
                result.add_warning("SELL direction but receiving non-base token")

    def _validate_protocol(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate protocol detection."""
        if trade.protocol not in DEXProtocol:
            result.add_error(f"Invalid protocol: {trade.protocol}")

        if trade.protocol == DEXProtocol.UNKNOWN:
            result.add_warning("Protocol not detected (UNKNOWN)")

    def _validate_amounts_positive(
        self,
        trade: NormalizedTrade,
        result: ValidationResult,
    ) -> None:
        """Validate amounts are positive (non-zero for swaps)."""
        if trade.token_in.amount == 0:
            result.add_warning("token_in.amount is zero")
        if trade.token_out.amount == 0:
            result.add_warning("token_out.amount is zero")

    def _validate_against_expected(
        self,
        trade: NormalizedTrade,
        expected: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """Validate trade matches expected values."""
        # Check wallet
        if "wallet" in expected and trade.wallet != expected["wallet"]:
            result.add_error(
                f"Wallet mismatch: expected {expected['wallet']}, got {trade.wallet}"
            )

        # Check direction
        if "direction" in expected and trade.direction.value != expected["direction"]:
            result.add_error(
                f"Direction mismatch: expected {expected['direction']}, got {trade.direction.value}"
            )

        # Check protocol
        if "protocol" in expected and trade.protocol.value != expected["protocol"]:
            result.add_error(
                f"Protocol mismatch: expected {expected['protocol']}, got {trade.protocol.value}"
            )

        # Check token_in
        if "token_in" in expected:
            exp_in = expected["token_in"]
            if "mint" in exp_in and trade.token_in.mint != exp_in["mint"]:
                result.add_error(
                    f"token_in.mint mismatch: expected {exp_in['mint']}, got {trade.token_in.mint}"
                )
            if "amount" in exp_in and str(trade.token_in.amount) != exp_in["amount"]:
                result.add_error(
                    f"token_in.amount mismatch: expected {exp_in['amount']}, got {trade.token_in.amount}"
                )
            if "decimals" in exp_in and trade.token_in.decimals != exp_in["decimals"]:
                result.add_error(
                    f"token_in.decimals mismatch: expected {exp_in['decimals']}, got {trade.token_in.decimals}"
                )

        # Check token_out
        if "token_out" in expected:
            exp_out = expected["token_out"]
            if "mint" in exp_out and trade.token_out.mint != exp_out["mint"]:
                result.add_error(
                    f"token_out.mint mismatch: expected {exp_out['mint']}, got {trade.token_out.mint}"
                )
            if "amount" in exp_out and str(trade.token_out.amount) != exp_out["amount"]:
                result.add_error(
                    f"token_out.amount mismatch: expected {exp_out['amount']}, got {trade.token_out.amount}"
                )
            if "decimals" in exp_out and trade.token_out.decimals != exp_out["decimals"]:
                result.add_error(
                    f"token_out.decimals mismatch: expected {exp_out['decimals']}, got {trade.token_out.decimals}"
                )

        # Check fee
        if "fee_sol" in expected and str(trade.fee_sol) != expected["fee_sol"]:
            result.add_error(
                f"fee_sol mismatch: expected {expected['fee_sol']}, got {trade.fee_sol}"
            )
