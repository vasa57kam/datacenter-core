import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Product, ProvisioningTask, ServiceInstance, VpnAccount, VpnNode,
)
from app.adapters.vpn import get_adapter

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RUNNING_TIMEOUT = timedelta(minutes=10)


def enqueue_task(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    payload: dict[str, Any] | None = None,
) -> ProvisioningTask:
    # Дедупликация: если такая же задача уже ждёт/выполняется — не плодим дубли.
    existing = db.execute(
        select(ProvisioningTask).where(
            ProvisioningTask.entity_type == entity_type,
            ProvisioningTask.entity_id == entity_id,
            ProvisioningTask.action == action,
            ProvisioningTask.status.in_(["pending", "running"]),
        )
    ).scalars().first()
    if existing:
        return existing

    task = ProvisioningTask(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        status="pending",
        payload=payload or {},
        idempotency_key=f"{entity_type}:{entity_id}:{action}:{uuid.uuid4().hex}",
    )
    db.add(task)
    db.flush()
    return task


def _execute_create(db: Session, service: ServiceInstance) -> dict:
    already = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if already is not None:  # повторный запуск после сбоя — аккаунт уже есть
        service.status = "active"
        return {"account_id": already.id, "skipped": True}

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
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.suspend_account(db, account))
    account.status = "suspended"
    return {"account_id": account.id}


def _execute_resume(db: Session, service: ServiceInstance) -> dict:
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.resume_account(db, account))
    account.status = "active"
    return {"account_id": account.id}


def _execute_delete(db: Session, service: ServiceInstance) -> dict:
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if not account:
        return {"skipped": True}
    
    node = db.get(VpnNode, account.node_id)
    adapter = get_adapter(node)
    asyncio.run(adapter.delete_account(db, account))
    account.status = "deleted"
    account.ip_address = None  # освободить адрес для повторной выдачи
    service.status = "terminated"
    return {"account_id": account.id}


ACTION_HANDLERS = {
    "create": _execute_create,
    "suspend": _execute_suspend,
    "resume": _execute_resume,
    "delete": _execute_delete,
}


def _run_task(task_id: int) -> bool:
    """Выполняет одну задачу в собственной сессии БД. True — выполнена успешно."""
    db = SessionLocal()
    try:
        # Захват задачи: SKIP LOCKED — несколько воркеров не возьмут одну и ту же.
        task = db.execute(
            select(ProvisioningTask)
            .where(ProvisioningTask.id == task_id, ProvisioningTask.status == "pending")
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if task is None:
            return False
        task.status = "running"
        task.attempts += 1
        db.commit()

        action, entity_type, entity_id = task.action, task.entity_type, task.entity_id
        try:
            handler = ACTION_HANDLERS.get(action)
            if not handler:
                raise ValueError(f"Unknown action: {action}")
            if entity_type != "service_instance":
                raise ValueError(f"Unsupported entity_type: {entity_type}")
            service = db.get(ServiceInstance, entity_id)
            if not service:
                raise ValueError(f"Service {entity_id} not found")

            result = handler(db, service)
            task.result = result
            task.status = "done"
            task.error = None
            db.commit()
            log.info("Task %s (%s) completed", task_id, action)
            return True
        except Exception as e:
            # Откатываем частичные изменения хэндлера и только потом фиксируем ошибку.
            db.rollback()
            log.exception("Task %s (%s) failed: %s", task_id, action, e)
            task = db.get(ProvisioningTask, task_id)
            task.error = str(e)[:500]
            if task.attempts < MAX_ATTEMPTS:
                task.status = "pending"  # повторим на следующем тике
            else:
                task.status = "error"
                if action == "create":
                    service = db.get(ServiceInstance, entity_id)
                    if service is not None and service.status == "provisioning":
                        service.status = "pending"
            db.commit()
            return False
    finally:
        db.close()


def process_pending_tasks_sync() -> int:
    """Обрабатывает pending tasks. Вызывается из worker."""
    db = SessionLocal()
    try:
        # Задачи, зависшие в running (воркер упал посреди выполнения), возвращаем в очередь.
        db.execute(
            update(ProvisioningTask)
            .where(
                ProvisioningTask.status == "running",
                ProvisioningTask.updated_at < datetime.now(timezone.utc) - RUNNING_TIMEOUT,
            )
            .values(status="pending")
        )
        db.commit()
        task_ids = db.execute(
            select(ProvisioningTask.id)
            .where(ProvisioningTask.status == "pending")
            .order_by(ProvisioningTask.id.asc())
            .limit(10)
        ).scalars().all()
    finally:
        db.close()

    return sum(1 for task_id in task_ids if _run_task(task_id))
