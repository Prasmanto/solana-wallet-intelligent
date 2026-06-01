from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WalletBase(BaseModel):
    address: str = Field(..., min_length=32, max_length=44, description="Solana wallet address")
    label: str | None = None
    tags: list[str] = Field(default_factory=list)


class WalletCreate(WalletBase):
    pass


class WalletUpdate(BaseModel):
    label: str | None = None
    tags: list[str] | None = None
    risk_score: float | None = None


class WalletRead(WalletBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    risk_score: float | None = None
    created_at: datetime
    updated_at: datetime
