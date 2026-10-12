import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Product, ProvisioningTask, ServiceInstance, VpnAccount, VpnNode,
)
from app.adapters.vpn import get_adapter

log = logging.getLogger(__name__)


def enqueue_task(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    payload: dict[str, Any] | None = None,
) -> ProvisioningTask:
    idem_key = f"{entity_type}:{entity_id}:{action}:{int(datetime.now(timezone.utc).timestamp())}"
    
    existing = db.execute(
        select(ProvisioningTask).where(ProvisioningTask.idempotency_key == idem_key)
    ).scalar_one_or_none()
    
    if existing:
        return existing
    
    task = ProvisioningTask(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        status="pending",
        payload=payload or {},
        idempotency_key=idem_key,
    )
    db.add(task)
    db.flush()
    return task


def _execute_create(db: Session, service: ServiceInstance) -> dict:
    node_id = service.config.get("node_id")
    if not node_id:
        raise ValueError("No node_id in service config")
    
    node = db.get(VpnNode, node_id)
    if not node or not node.active:
        raise ValueError(f"Node {node_id} not available")
    
    product = db.get(Product, service.product_id)
    adapter = get_adapter(node)
    
    result = asyncio.run(adapter.create_account(db, service, product))
    
    account = VpnAccount(
        service_instance_id=service.id,
        node_id=node.id,
        protocol=node.protocol,
        external_id=result["external_id"],
        username=result["username"],
        uuid=result.get("uuid"),
        ip_address=result.get("ip_address"),
        secret_enc=result["secret_enc"],
        public_key=result.get("public_key"),
        status="active",
        extra=result.get("extra", {}),
    )
    db.add(account)
    service.status = "active"
    db.flush()
    
    return {"account_id": account.id, "username": account.username}


def _execute_suspend(db: Session, service: ServiceInstance) -> dict:
    from app.models import VpnAccount
    account = db.query(VpnAccount).filter_by(service_instance_id=service.id).first()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.suspend_account(db, account))
    account.status = "suspended"
    return {"account_id": account.id}


def _execute_resume(db: Session, service: ServiceInstance) -> dict:
    from app.models import VpnAccount
    account = db.query(VpnAccount).filter_by(service_instance_id=service.id).first()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.resume_account(db, account))
    account.status = "active"
    return {"account_id": account.id}


def _execute_delete(db: Session, service: ServiceInstance) -> dict:
    from app.models import VpnAccount
    account = db.query(VpnAccount).filter_by(service_instance_id=service.id).first()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.delete_account(db, account))
    account.status = "deleted"
    service.status = "terminated"
    return {"account_id": account.id}


ACTION_HANDLERS = {
    "create": _execute_create,
    "suspend": _execute_suspend,
    "resume": _execute_resume,
    "delete": _execute_delete,
}


def process_pending_tasks_sync() -> int:
    """Обрабатывает pending tasks. Вызывается из worker."""
    db = SessionLocal()
    processed = 0
    
    try:
        tasks = db.execute(
            select(ProvisioningTask)
            .where(ProvisioningTask.status == "pending")
            .order_by(ProvisioningTask.id.asc())
            .limit(10)
        ).scalars().all()
        
        for task in tasks:
            task.status = "running"
            task.attempts += 1
            db.flush()
            
            try:
                handler = ACTION_HANDLERS.get(task.action)
                if not handler:
                    raise ValueError(f"Unknown action: {task.action}")
                
                if task.entity_type == "service_instance":
                    service = db.get(ServiceInstance, task.entity_id)
                    if not service:
                        raise ValueError(f"Service {task.entity_id} not found")
                    
                    result = handler(db, service)
                    task.result = result
                    task.status = "done"
                    task.error = None
                
                processed += 1
                log.info(f"Task {task.id} ({task.action}) completed: {result}")
                
            except Exception as e:
                log.exception(f"Task {task.id} failed: {e}")
                task.status = "error"
                task.error = str(e)[:500]
            
            db.commit()
    
    finally:
        db.close()
    
    return processed
