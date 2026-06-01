from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wallet_id: uuid.UUID
    signature: str
    slot: int
    block_time: datetime | None = None
    tx_type: str
    program_id: str | None = None
    amount: Decimal | None = None
    mint: str | None = None
    status: str
    created_at: datetime
