import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.vpn import get_adapter
from app.services import ledger
from app.db import SessionLocal
from app.models import (
    Product, ProvisioningTask, ServiceInstance, VpnAccount, VpnNode,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def enqueue_task(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    payload: dict[str, Any] | None = None,
) -> ProvisioningTask:
    stuck = ("pending", "running")
    existing = db.execute(
        select(ProvisioningTask).where(
            ProvisioningTask.entity_type == entity_type,
            ProvisioningTask.entity_id == entity_id,
            ProvisioningTask.action == action,
            ProvisioningTask.status.in_(stuck),
        )
    ).scalars().first()
    if existing:
        return existing

    idem_key = f"{entity_type}:{entity_id}:{action}:{int(datetime.now(timezone.utc).timestamp())}"
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
    existing = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if existing:
        service.status = "active"
        return {"account_id": existing.id, "already": True}

    node_id = service.config.get("node_id")
    if not node_id:
        raise ValueError("No node_id in service config")
    node = db.get(VpnNode, node_id)
    if not node or not node.active:
        raise ValueError(f"Node {node_id} not available")
    product = db.get(Product, service.product_id)

    result = asyncio.run(get_adapter(node).create_account(db, service, product))

    product_unit = product.unit if product else "minute"
    if product_unit in ("month", "one_time") and product:
        wallet = ledger.get_wallet(db, service.user_id)
        try:
            ledger.debit(
                db, wallet, product.price_minor,
                reason=f"service_activation_{product_unit}",
                entity_type="service_instance",
                entity_id=service.id,
                idempotency_key=f"activate:{service.id}:{product_unit}",
            )
        except ledger.InsufficientFunds:
            raise ValueError("Insufficient balance for prepaid activation")
    account = VpnAccount(
        service_instance_id=service.id,
        node_id=node.id,
        protocol=node.protocol,
        external_id=result["external_id"],
        username=result["username"],
        uuid=result.get("uuid"),
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
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if not account:
        return {"skipped": True}
    asyncio.run(get_adapter(db.get(VpnNode, account.node_id)).suspend_account(db, account))
    account.status = "suspended"
    return {"account_id": account.id}


def _execute_resume(db: Session, service: ServiceInstance) -> dict:
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if not account:
        return {"skipped": True}
    asyncio.run(get_adapter(db.get(VpnNode, account.node_id)).resume_account(db, account))
    account.status = "active"
    return {"account_id": account.id}


def _execute_delete(db: Session, service: ServiceInstance) -> dict:
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if account:
        node = db.get(VpnNode, account.node_id)
        if node:
            try:
                asyncio.run(get_adapter(node).delete_account(db, account))
            except Exception as e:
                log.warning("panel delete failed: %s", e)
    db.delete(service)
    db.flush()
    return {"deleted": True}


ACTION_HANDLERS = {
    "create": _execute_create,
    "suspend": _execute_suspend,
    "resume": _execute_resume,
    "delete": _execute_delete,
}


def recover_stuck_tasks() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        stuck = db.execute(
            select(ProvisioningTask).where(
                ProvisioningTask.status == "running",
                ProvisioningTask.updated_at < cutoff,
            )
        ).scalars().all()
        for t in stuck:
            t.status = "pending"
        if stuck:
            db.commit()
            log.info("recovered %s stuck tasks", len(stuck))
    finally:
        db.close()


def process_pending_tasks_sync() -> int:
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
            db.commit()

            try:
                handler = ACTION_HANDLERS.get(task.action)
                if handler is None:
                    raise ValueError(f"Unknown action: {task.action}")
                if task.entity_type != "service_instance":
                    raise ValueError(f"Unknown entity_type: {task.entity_type}")
                service = db.get(ServiceInstance, task.entity_id)
                if service is None:
                    raise ValueError(f"Service {task.entity_id} not found")

                result = handler(db, service)
                task.result = result or {}
                task.status = "done"
                task.error = None
                processed += 1
                log.info("task %s (%s) done", task.id, task.action)
                db.commit()
            except Exception as e:
                log.exception("task %s (%s) failed: %s", task.id, task.action, e)
                db.rollback()
                task = db.get(ProvisioningTask, task.id)
                task.error = str(e)[:500]
                task.status = "error" if task.attempts >= MAX_ATTEMPTS else "pending"
                db.commit()
    finally:
        db.close()
    return processed


def process_task_now(db: Session, task_id: int) -> None:
    """Выполняет задачу синхронно в текущей сессии (для мгновенного отказа)."""
    task = db.get(ProvisioningTask, task_id)
    if task is None or task.status not in ("pending", "error"):
        return
    task.status = "running"
    task.attempts += 1
    db.flush()
    try:
        handler = ACTION_HANDLERS.get(task.action)
        if handler is None:
            raise ValueError(f"Unknown action: {task.action}")
        service = db.get(ServiceInstance, task.entity_id)
        if service is None:
            raise ValueError(f"Service {task.entity_id} not found")
        result = handler(db, service)
        task.result = result or {}
        task.status = "done"
        task.error = None
    except Exception as e:
        log.exception("task %s failed: %s", task_id, e)
        db.rollback()
        task = db.get(ProvisioningTask, task_id)
        if task is not None:
            task.status = "pending"
            task.error = str(e)[:500]
