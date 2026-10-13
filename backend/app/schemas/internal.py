from pydantic import BaseModel, EmailStr, Field


class VpnUsageItem(BaseModel):
    vpn_account_id: int
    external_session_id: str | None = None
    active: bool = True
    rx_bytes: int = 0
    tx_bytes: int = 0


class VpnUsagePayload(BaseModel):
    node_code: str
    sessions: list[VpnUsageItem]


class CctvUserEnsureRequest(BaseModel):
    cctv_username: str
    email: EmailStr | None = None


class CctvOrderRequest(BaseModel):
    cctv_username: str | None = None
    user_email: EmailStr | None = None
    camera_id: str
    months: int = Field(default=1, ge=1, le=120)
    price_minor: int | None = Field(default=None, ge=0)
    idempotency_key: str


class CctvChargeRequest(BaseModel):
    cctv_username: str | None = None
    user_id: int | None = None
    amount_minor: int = Field(gt=0)
    reason: str = "cctv_subscription"
    idempotency_key: str


class CctvCreditRequest(BaseModel):
    cctv_username: str | None = None
    user_id: int | None = None
    amount_minor: int = Field(gt=0)
    reason: str = "cctv_topup"
    idempotency_key: str
