from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WalletOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    currency: str
    balance_minor: int


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    amount_minor: int
    balance_after_minor: int
    entry_type: str
    reason: str
    created_at: datetime
