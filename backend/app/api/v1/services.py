from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Product, ServiceInstance, User, VpnNode
from app.services.provisioning import enqueue_task

router = APIRouter(prefix="/api/v1/services", tags=["services"])


class CreateVpnService(BaseModel):
    product_code: str
    node_code: str | None = None
    name: str | None = None


@router.post("/vpn")
def create_vpn_service(
    payload: CreateVpnService,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter_by(code=payload.product_code, active=True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Выбираем ноду
    node = None
    if payload.node_code:
        node = db.query(VpnNode).filter_by(code=payload.node_code, active=True).first()
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {payload.node_code} not found")
    else:
        # Автоматический выбор первой активной ноды нужного протокола
        proto = product.config.get("protocol", "vless")
        node = db.query(VpnNode).filter_by(protocol=proto, active=True).first()
    
    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=payload.name or f"{product.name} @ {node.code}" if node else product.name,
        status="provisioning" if node else "pending",
        config={"node_id": node.id} if node else {},
    )
    db.add(service)
    db.flush()
    
    if node:
        enqueue_task(db, "service_instance", service.id, "create")
    
    db.commit()
    return {
        "id": service.id,
        "user_id": service.user_id,
        "product_id": service.product_id,
        "name": service.name,
        "status": service.status,
        "created_at": service.created_at.isoformat(),
    }


@router.get("/{service_id}/config")
def get_service_config(
    service_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from app.adapters.vpn import get_adapter
    
    service = db.get(ServiceInstance, service_id)
    if not service or service.user_id != user.id:
        raise HTTPException(status_code=404, detail="Service not found")
    
    if service.status == "provisioning":
        raise HTTPException(status_code=202, detail="Still provisioning, try again in 15 seconds")
    
    account = service.accounts.first() if hasattr(service, 'accounts') else None
    if not account:
        from app.models import VpnAccount
        account = db.query(VpnAccount).filter_by(service_instance_id=service.id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not provisioned yet")
    
    from app.models import VpnNode
    node = db.get(VpnNode, account.node_id)
    cfg = get_adapter(node).render_config(db, account)
    
    return {
        "service_id": service.id,
        "account_username": account.username,
        "link": cfg.get("link"),
        "subscription_url": cfg.get("subscription_url"),
        "config_text": cfg.get("config_text"),
    }
