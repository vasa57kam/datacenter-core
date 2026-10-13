import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db import SessionLocal
from app.models import Product, ServiceInstance, UsageSession, VpnAccount, VpnNode
from app.services import ledger
from app.services.provisioning import enqueue_task

log = logging.getLogger(__name__)

TICK_SECONDS = {"second": 1, "minute": 60}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def report_usage(db, node: VpnNode, item) -> UsageSession | None:
    account = db.get(VpnAccount, item.vpn_account_id)
    if account is None or account.node_id != node.id or account.status != "active":
        return None
    service = db.get(ServiceInstance, account.service_instance_id)
    if service is None or service.status != "active":
        return None

    session = db.execute(
        select(UsageSession).where(
            UsageSession.vpn_account_id == account.id,
            UsageSession.status == "active",
        )
    ).scalar_one_or_none()

    if not item.active:
        if session is not None:
            session.status = "closed"
            session.ended_at = utcnow()
        db.flush()
        return session

    if session is None:
        session = UsageSession(
            service_instance_id=service.id,
            vpn_account_id=account.id,
            node_id=node.id,
            external_session_id=item.external_session_id,
            started_at=utcnow(),
            last_heartbeat_at=utcnow(),
            status="active",
        )
        db.add(session)
    else:
        session.last_heartbeat_at = utcnow()
        if item.external_session_id and not session.external_session_id:
            session.external_session_id = item.external_session_id

    session.rx_bytes = item.rx_bytes
    session.tx_bytes = item.tx_bytes
    db.flush()
    return session


def _suspend(db, service: ServiceInstance, session: UsageSession) -> None:
    if service.status != "suspended":
        service.status = "suspended"
        enqueue_task(db, "service_instance", service.id, "suspend")
    session.status = "closed"
    session.ended_at = utcnow()
    db.commit()


def charge_active_sessions() -> None:
    db = SessionLocal()
    try:
        sessions = db.execute(
            select(UsageSession).where(UsageSession.status == "active")
        ).scalars().all()
        if not sessions:
            return
        for session in sessions:
            service = db.get(ServiceInstance, session.service_instance_id)
            if service is None or service.status != "active":
                session.status = "closed"
                session.ended_at = utcnow()
                db.commit()
                continue
            product = db.get(Product, service.product_id)
            if product is None or product.unit not in TICK_SECONDS:
                continue
            tick = TICK_SECONDS[product.unit]
            wallet = ledger.get_wallet(db, service.user_id)
            elapsed = int((utcnow() - session.started_at).total_seconds())
            ticks = elapsed // tick
            charged = 0
            for n in range(session.charged_minutes + 1, ticks + 1):
                key = f"usage:session:{session.id}:tick:{n}"
                try:
                    ledger.debit(
                        db, wallet, product.price_minor,
                        reason=f"vpn_usage_{product.unit}",
                        entity_type="usage_session",
                        entity_id=session.id,
                        idempotency_key=key,
                    )
                except ledger.InsufficientFunds:
                    _suspend(db, service, session)
                    break
                session.charged_minutes = n
                session.cost_minor += product.price_minor
                charged += 1
            db.commit()
            if charged:
                log.info("session %s charged %s tick(s)", session.id, charged)
    finally:
        db.close()


def close_stale_sessions() -> None:
    cutoff = utcnow() - timedelta(seconds=settings.heartbeat_grace_seconds)
    db = SessionLocal()
    try:
        stale = db.execute(
            select(UsageSession).where(
                UsageSession.status == "active",
                UsageSession.last_heartbeat_at < cutoff,
            )
        ).scalars().all()
        for session in stale:
            session.status = "closed"
            session.ended_at = session.last_heartbeat_at
        if stale:
            log.info("closed %s stale session(s)", len(stale))
        db.commit()
    finally:
        db.close()
