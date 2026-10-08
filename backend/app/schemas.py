from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    status: str


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


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    service_type: str
    name: str
    unit: str
    price_minor: int
    currency: str


class CreateVpnServiceRequest(BaseModel):
    product_code: str
    node_code: str
    name: str | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    product_id: int
    name: str
    status: str
    created_at: datetime


class ServiceConfigOut(BaseModel):
    service_id: int
    protocol: str
    link: str | None = None
    subscription_url: str | None = None
    config_text: str | None = None


class AdminCreditRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    reason: str = "manual_topup"
    idempotency_key: str


class AdminProductRequest(BaseModel):
    code: str
    name: str
    service_type: str
    unit: str
    price_minor: int = Field(ge=0)
    config: dict = {}


class AdminNodeRequest(BaseModel):
    code: str
    name: str
    country: str
    protocol: str
    api_kind: str
    api_url: str | None = None
    api_user: str | None = None
    api_key: str | None = None
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    ssh_key: str | None = None
    subnet_cidr: str | None = None
    endpoint_host: str | None = None
    endpoint_port: int | None = None
    public_key: str | None = None
    extra: dict = {}


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