from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_internal_key
from app.models import Product, ServiceInstance, User
from app.schemas import CctvOrderRequest

router = APIRouter(prefix="/internal/v1/cctv", tags=["internal"])


@router.post("/orders", status_code=202)
def cctv_order(
    body: CctvOrderRequest,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    """Заглушка моста к CCTV Cloud: фиксирует заказ, реальная выдача — в спринте 2."""
    user = db.execute(select(User).where(User.email == body.user_email)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    product = db.execute(
        select(Product).where(Product.code == "cctv-camera-month")
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product cctv-camera-month not found")

    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=f"CCTV camera {body.camera_id}",
        status="pending",
        config={"camera_id": body.camera_id, "months": body.months, "idempotency_key": body.idempotency_key},
    )
    db.add(service)
    db.commit()
    return {"status": "accepted", "service_instance_id": service.id}