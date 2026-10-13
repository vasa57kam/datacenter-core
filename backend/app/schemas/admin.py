from typing import Literal

from pydantic import BaseModel, Field


class AdminCreditRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    reason: str = "manual_topup"
    idempotency_key: str


class AdminProductRequest(BaseModel):
    code: str
    name: str
    service_type: Literal["vpn", "vps", "cctv", "hosting", "storage", "mail"]
    unit: Literal["second", "minute", "hour", "day", "month", "one_time"]
    price_minor: int = Field(ge=0)
    config: dict = {}


class AdminNodeRequest(BaseModel):
    code: str
    name: str
    country: str
    protocol: Literal["vless", "wireguard", "openvpn"]
    api_kind: Literal["3xui", "marzban", "ssh_wireguard", "openvpn_api", "manual"]
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
