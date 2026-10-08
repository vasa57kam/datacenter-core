import asyncio
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.vpn import get_adapter
from app.db import SessionLocal
from app.models import (
    Product, ProvisioningTask, ServiceInstance, VpnAccount, VpnNode,
)


def enqueue_task(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> ProvisioningTask:
    if idempotency_key is None:
        if action == "create":
            idempotency_key = f"{entity_type}:{entity_id}:create"
        else:
            idempotency_key = f"{entity_type}:{entity_id}:{action}:{int(time.time() * 1000)}"
    task = ProvisioningTask(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    db.add(task)
    db.flush()
    return task


async def run_task(db: Session, task: ProvisioningTask) -> None:
    task.status = "running"
    task.attempts += 1
    db.commit()

    service = db.get(ServiceInstance, task.entity_id)
    if service is None:
        task.status = "error"
        task.error = "service not found"
        db.commit()
        return

    node = db.get(VpnNode, int(service.config.get("node_id", 0)))
    if node is None:
        task.status = "error"
        task.error = "node not found"
        db.commit()
        return

    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()

    adapter = get_adapter(node)
    product = db.get(Product, service.product_id)

    try:
        if task.action == "create":
            data = await adapter.create_account(db, service, product)
            account = VpnAccount(
                service_instance_id=service.id,
                node_id=node.id,
                protocol=node.protocol,
                external_id=data.get("external_id"),
                username=data.get("username"),
                uuid=data.get("uuid"),
                ip_address=data.get("ip_address"),
                secret_enc=data.get("secret_enc"),
                public_key=data.get("public_key"),
                extra=data.get("extra", {}),
                status="active",
            )
            db.add(account)
            service.status = "active"
        elif task.action == "suspend":
            await adapter.suspend_account(db, account)
            account.status = "suspended"
        elif task.action == "resume":
            await adapter.resume_account(db, account)
            account.status = "active"
            service.status = "active"
        elif task.action == "delete":
            await adapter.delete_account(db, account)
            account.status = "deleted"
            service.status = "terminated"
        task.status = "done"
        task.error = None
    except Exception as exc:  # noqa: BLE001
        task.status = "error"
        task.error = str(exc)

    db.commit()


async def process_pending_tasks() -> None:
    db = SessionLocal()
    try:
        tasks = db.execute(
            select(ProvisioningTask)
            .where(ProvisioningTask.status.in_(["pending", "error"]))
            .where(ProvisioningTask.attempts < 5)
            .order_by(ProvisioningTask.id)
            .limit(10)
        ).scalars().all()
        for task in tasks:
            await run_task(db, task)
    finally:
        db.close()


def process_pending_tasks_sync() -> None:
    asyncio.run(process_pending_tasks())