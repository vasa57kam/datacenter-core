from pydantic import BaseModel, EmailStr


class VpnUsageItem(BaseModel):
    vpn_account_id: int
    external_session_id: str | None = None
    active: bool = True
    rx_bytes: int = 0
    tx_bytes: int = 0


class VpnUsagePayload(BaseModel):
    node_code: str
    sessions: list[VpnUsageItem]


class CctvOrderRequest(BaseModel):
    user_email: EmailStr
    camera_id: str
    months: int = 1
    idempotency_key: str
