"""Helius webhook payload models.

Defines the Pydantic schemas for Helius Enhanced Webhook payloads.
Helius sends batched transaction data with various event types.

Reference: https://docs.helius.dev/webhooks-and-websockets/webhooks
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WebhookTransactionType(str, Enum):
    """Helius transaction event types."""

    TRANSFER = "TRANSFER"
    SWAP = "SWAP"
    UNKNOWN = "UNKNOWN"


class WebhookNFTEvent(BaseModel):
    """NFT-related event data."""

    from_account: str = ""
    to_account: str = ""
    token_amount: float = 0
    mint: str = ""


class WebhookTokenTransfer(BaseModel):
    """Token transfer event data."""

    from_user_account: str = ""
    to_user_account: str = ""
    token_amount: float = 0
    mint: str = ""
    token_standard: str = ""


class WebhookAccountData(BaseModel):
    """Account change data."""

    account: str = ""
    native_balance_change: int = 0
    token_balance_changes: list[dict[str, Any]] = Field(default_factory=list)


class WebhookTransaction(BaseModel):
    """A single transaction from Helius webhook.

    Helius sends transactions with the following structure:
    - signature: Transaction signature
    - slot: Solana slot
    - timestamp: Block timestamp
    - type: Event type (TRANSFER, SWAP, etc.)
    - source: Source program
    - fee: Transaction fee in lamports
    - fee_payer: Fee payer address
    - description: Human-readable description
    - accountData: Account balance changes
    - tokenTransfers: Token transfer details
    - nativeTransfers: SOL transfer details
    """

    signature: str
    slot: int
    timestamp: int | None = None
    type: str = "UNKNOWN"
    source: str = ""
    fee: int = 0
    fee_payer: str = ""
    description: str = ""
    account_data: list[WebhookAccountData] = Field(
        default_factory=list,
        alias="accountData",
    )
    token_transfers: list[WebhookTokenTransfer] = Field(
        default_factory=list,
        alias="tokenTransfers",
    )
    native_transfers: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="nativeTransfers",
    )
    events: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class HeliusWebhookPayload(BaseModel):
    """Helius Enhanced Webhook payload.

    Helius sends a JSON body with:
    - webhookID: The webhook identifier
    - transaction: The transaction data (or transactions for batched)
    - webhookType: e.g., "enhanced"
    - cluster: e.g., "mainnet-beta"

    For batched webhooks, the payload contains multiple transactions.
    """

    webhook_id: str = Field(
        default="",
        alias="webhookID",
    )
    webhook_type: str = Field(
        default="enhanced",
        alias="webhookType",
    )
    cluster: str = "mainnet-beta"
    transaction: WebhookTransaction | None = None
    # Batched webhooks may use different field names
    transactions: list[WebhookTransaction] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("transactions", mode="before")
    @classmethod
    def normalize_transactions(cls, v: list | None) -> list:
        """Normalize transaction list (handle single vs batched)."""
        if v is None:
            return []
        return v

    @property
    def all_transactions(self) -> list[WebhookTransaction]:
        """Get all transactions (single or batched)."""
        txs = []
        if self.transaction:
            txs.append(self.transaction)
        txs.extend(self.transactions)
        return txs

    @property
    def transaction_count(self) -> int:
        """Get total transaction count."""
        count = len(self.transactions)
        if self.transaction:
            count += 1
        return count


class WebhookIngestionResult(BaseModel):
    """Result of webhook ingestion processing."""

    success: bool
    transactions_processed: int = 0
    events_persisted: int = 0
    events_published: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    correlation_ids: list[str] = Field(default_factory=list)


class WebhookValidationResult(BaseModel):
    """Result of webhook validation."""

    valid: bool
    error: str | None = None
    webhook_id: str | None = None
