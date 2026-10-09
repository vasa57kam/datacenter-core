from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
