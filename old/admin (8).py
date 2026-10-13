from pydantic import BaseModel, Field


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
