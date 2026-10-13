from pydantic import BaseModel, ConfigDict


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    service_type: str
    name: str
    unit: str
    price_minor: int
    currency: str
