from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user as current_user
from app.models import Product, ServiceInstance, User, VpnNode, VpnAccount
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
    product = db.execute(
        select(Product).where(Product.code == payload.product_code, Product.active == True)
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Выбираем ноду
    node = None
    if payload.node_code:
        node = db.execute(
            select(VpnNode).where(VpnNode.code == payload.node_code, VpnNode.active == True)
        ).scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {payload.node_code} not found")
    else:
        # Автоматический выбор первой активной ноды нужного протокола
        proto = product.config.get("protocol", "vless")
        node = db.execute(
            select(VpnNode).where(VpnNode.protocol == proto, VpnNode.active == True)
        ).scalars().first()
    
    # Правильный приоритет операторов
    if payload.name:
        service_name = payload.name
    elif node:
        service_name = f"{product.name} @ {node.code}"
    else:
        service_name = product.name
    
    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=service_name,
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
    
    # accounts - это list (lazy="selectin"), не Query
    account = None
    if hasattr(service, 'accounts') and service.accounts:
        account = service.accounts[0] if service.accounts else None
    
    if not account:
        account = db.execute(
            select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
        ).scalar_one_or_none()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not provisioned yet")
    
    node = db.get(VpnNode, account.node_id)
    if not node:
        raise HTTPException(status_code=500, detail="VPN node not found")
    
    cfg = get_adapter(node).render_config(db, account)
    
    return {
        "service_id": service.id,
        "account_username": account.username,
        "link": cfg.get("link"),
        "subscription_url": cfg.get("subscription_url"),
        "config_text": cfg.get("config_text"),
    }


@router.delete("/{service_id}")
def delete_service(
    service_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Физическое удаление услуги с каскадом (аккаунт, сессии)."""
    service = db.get(ServiceInstance, service_id)
    if not service or service.user_id != user.id:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Создаём задачу на удаление
    enqueue_task(db, "service_instance", service.id, "delete")
    db.commit()
    
    return {"ok": True, "message": "Service deletion queued"}
