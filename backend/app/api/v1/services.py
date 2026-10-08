from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.vpn import get_adapter
from app.db import get_db
from app.deps import get_current_user
from app.models import Product, ServiceInstance, User, VpnAccount, VpnNode
from app.schemas import (
    CreateVpnServiceRequest, ServiceConfigOut, ServiceOut,
)
from app.services import ledger
from app.services.provisioning import enqueue_task

router = APIRouter(prefix="/api/v1/services", tags=["services"])


def _get_own_service(db: Session, user: User, service_id: int) -> ServiceInstance:
    service = db.get(ServiceInstance, service_id)
    if service is None or service.user_id != user.id:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.post("/vpn", response_model=ServiceOut, status_code=202)
def create_vpn_service(
    body: CreateVpnServiceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = db.execute(
        select(Product).where(Product.code == body.product_code, Product.active.is_(True))
    ).scalar_one_or_none()
    if product is None or product.service_type != "vpn":
        raise HTTPException(status_code=404, detail="Product not found")

    node = db.execute(
        select(VpnNode).where(VpnNode.code == body.node_code, VpnNode.active.is_(True))
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.protocol != product.config.get("protocol"):
        raise HTTPException(status_code=400, detail="Protocol mismatch")

    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=body.name or f"{product.name} @ {node.code}",
        status="provisioning",
        config={"node_id": node.id},
    )
    db.add(service)
    db.flush()
    enqueue_task(db, "service_instance", service.id, "create")
    db.commit()
    return service


@router.get("", response_model=list[ServiceOut])
def list_services(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(
        select(ServiceInstance).where(ServiceInstance.user_id == user.id)
    ).scalars().all()


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(service_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_own_service(db, user, service_id)


@router.get("/{service_id}/config", response_model=ServiceConfigOut)
def get_service_config(service_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _get_own_service(db, user, service_id)
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=409, detail="Account not provisioned yet")
    node = db.get(VpnNode, account.node_id)
    cfg = get_adapter(node).render_config(db, account)
    return ServiceConfigOut(service_id=service.id, protocol=account.protocol, **cfg)


@router.post("/{service_id}/suspend", response_model=ServiceOut)
def suspend_service(service_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _get_own_service(db, user, service_id)
    service.status = "suspended"
    enqueue_task(db, "service_instance", service.id, "suspend")
    db.commit()
    return service


@router.post("/{service_id}/resume", response_model=ServiceOut)
def resume_service(service_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _get_own_service(db, user, service_id)
    wallet = ledger.get_wallet(db, user.id)
    if wallet.balance_minor <= 0:
        raise HTTPException(status_code=402, detail="Top up balance first")
    service.status = "active"
    enqueue_task(db, "service_instance", service.id, "resume")
    db.commit()
    return service


@router.delete("/{service_id}", status_code=202)
def delete_service(service_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _get_own_service(db, user, service_id)
    enqueue_task(db, "service_instance", service.id, "delete")
    db.commit()
    return {"status": "delete scheduled"}