from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Product
from app.schemas import ProductOut

router = APIRouter(prefix="/api/v1/products", tags=["catalog"])


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    products = db.execute(select(Product).where(Product.active.is_(True))).scalars().all()
    return products