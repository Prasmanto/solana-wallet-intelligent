"""Normalized trade schema.

Defines the Pydantic models for normalized trade events.
This is the output of the parser stage and input to analytics.

Design:
- Protocol-agnostic: all DEXes produce the same schema
- Decimal-normalized: amounts are human-readable (not lamports)
- Full traceability: links back to raw event via correlation_id
- Queryable: fields indexed for analytics
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TradeDirection(str, Enum):
    """Trade direction relative to the wallet."""

    BUY = "buy"    # wallet received token_out, paid token_in
    SELL = "sell"   # wallet received token_in, paid token_out


class DEXProtocol(str, Enum):
    """Supported DEX protocols."""

    JUPITER = "jupiter"
    RAYDIUM = "raydium"
    PUMP_FUN = "pump.fun"
    ORCA = "orca"
    PHOTON = "photon"
    UNKNOWN = "unknown"


class TokenInfo(BaseModel):
    """Token information for input or output."""

    mint: str = Field(..., description="Token mint address")
    symbol: str = Field(default="", description="Token symbol (e.g., SOL, USDC)")
    name: str = Field(default="", description="Token name")
    decimals: int = Field(default=9, description="Token decimals")
    amount_raw: int = Field(default=0, description="Raw amount (lamports/smallest unit)")
    amount: Decimal = Field(default=Decimal("0"), description="Human-readable amount")

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, v: Any) -> Decimal:
        """Convert various types to Decimal."""
        if isinstance(v, Decimal):
            return v
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return Decimal("0")


class NormalizedTrade(BaseModel):
    """Normalized trade event.

    This is the canonical output of the parser stage.
    All DEXes (Jupiter, Raydium, Pump.fun, etc.) produce this same schema.
    """

    # ── Trade Identity ──────────────────────────────────────
    trade_id: str = Field(
        ...,
        description="Unique trade ID (derived from signature + index)",
    )
    signature: str = Field(
        ...,
        description="Solana transaction signature",
    )
    slot: int = Field(
        ...,
        description="Solana slot number",
    )
    timestamp: datetime | None = Field(
        default=None,
        description="Block timestamp",
    )

    # ── Wallet ──────────────────────────────────────────────
    wallet: str = Field(
        ...,
        description="Wallet address that executed the trade",
    )
    direction: TradeDirection = Field(
        ...,
        description="Trade direction (buy/sell relative to wallet)",
    )

    # ── Tokens ──────────────────────────────────────────────
    token_in: TokenInfo = Field(
        ...,
        description="Token being sold/paid",
    )
    token_out: TokenInfo = Field(
        ...,
        description="Token being received",
    )

    # ── Protocol ────────────────────────────────────────────
    protocol: DEXProtocol = Field(
        default=DEXProtocol.UNKNOWN,
        description="DEX protocol used",
    )
    protocol_program: str = Field(
        default="",
        description="On-chain program ID",
    )
    protocol_label: str = Field(
        default="",
        description="Human-readable protocol name from Helius",
    )

    # ── Fees ────────────────────────────────────────────────
    fee_sol: Decimal = Field(
        default=Decimal("0"),
        description="Transaction fee in SOL",
    )
    fee_token: TokenInfo | None = Field(
        default=None,
        description="Fee paid in token (if non-SOL fee)",
    )

    # ── Pipeline Metadata ───────────────────────────────────
    raw_event_id: str = Field(
        default="",
        description="ID of the raw event this was parsed from",
    )
    correlation_id: str = Field(
        default="",
        description="Correlation ID for pipeline tracing",
    )
    parser_version: str = Field(
        default="1.0.0",
        description="Parser version for schema evolution",
    )
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When this trade was parsed",
    )

    # ── Raw Data (optional, for debugging) ──────────────────
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original Helius transaction data",
    )


class ParseResult(BaseModel):
    """Result of parsing a single transaction."""

    success: bool
    trade: NormalizedTrade | None = None
    error: str | None = None
    error_code: str | None = None
    warnings: list[str] = Field(default_factory=list)


class BatchParseResult(BaseModel):
    """Result of parsing a batch of transactions."""

    total: int = 0
    success_count: int = 0
    error_count: int = 0
    trades: list[NormalizedTrade] = Field(default_factory=list)
    errors: list[ParseResult] = Field(default_factory=list)
