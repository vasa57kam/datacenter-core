import logging

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models import (
    Product, ServiceInstance, UsageSession, VpnAccount, VpnNode,
)
from app.services import ledger
from app.services.provisioning import enqueue_task

log = logging.getLogger(__name__)

TICK_SECONDS = {"second": 1, "minute": 60}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def report_usage(db: Session, node: VpnNode, item) -> UsageSession | None:
    account = db.get(VpnAccount, item.vpn_account_id)
    if account is None or account.node_id != node.id:
        return None
    if account.status != "active":
        return None
    service = db.get(ServiceInstance, account.service_instance_id)
    if service is None or service.status != "active":
        return None

    def _active_session() -> UsageSession | None:
        return db.execute(
            select(UsageSession).where(
                UsageSession.vpn_account_id == account.id,
                UsageSession.status == "active",
            )
        ).scalar_one_or_none()

    session = _active_session()

    if not item.active:
        if session is not None:
            session.status = "closed"
            session.ended_at = utcnow()
        db.flush()
        return session

    now = utcnow()
    if session is None:
        try:
            # savepoint + частичный уникальный индекс: две одновременные
            # «первые» отчётности не создадут две активные сессии (двойное списание)
            with db.begin_nested():
                session = UsageSession(
                    service_instance_id=service.id,
                    vpn_account_id=account.id,
                    node_id=node.id,
                    external_session_id=item.external_session_id,
                    started_at=now,
                    last_heartbeat_at=now,
                    status="active",
                )
                db.add(session)
                db.flush()
        except IntegrityError:
            session = _active_session()
            if session is None:
                return None
    else:
        session.last_heartbeat_at = now
        if item.external_session_id and not session.external_session_id:
            session.external_session_id = item.external_session_id

    session.rx_bytes = max(item.rx_bytes, 0)
    session.tx_bytes = max(item.tx_bytes, 0)
    db.flush()
    return session


def _suspend(db: Session, service: ServiceInstance, session: UsageSession) -> None:
    if service.status != "suspended":
        service.status = "suspended"
        enqueue_task(db, "service_instance", service.id, "suspend")
    session.status = "closed"
    session.ended_at = utcnow()
    db.commit()


def _charge_session(db: Session, session_id: int) -> int:
    """Списывает недостающие тики по одной сессии. Возвращает число списанных тиков."""
    # Блокируем строку сессии: параллельный report_usage/close_stale не изменит её посреди списания.
    session = db.execute(
        select(UsageSession)
        .where(UsageSession.id == session_id, UsageSession.status == "active")
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if session is None:
        return 0

    service = db.get(ServiceInstance, session.service_instance_id)
    if service is None or service.status != "active":
        session.status = "closed"
        session.ended_at = utcnow()
        db.commit()
        return 0

    product = db.get(Product, service.product_id)
    if product is None or product.unit not in TICK_SECONDS or product.price_minor <= 0:
        return 0

    tick = TICK_SECONDS[product.unit]
    wallet = ledger.get_wallet(db, service.user_id)
    elapsed = int((utcnow() - session.started_at).total_seconds())
    ticks = elapsed // tick

    charged = 0
    for n in range(session.charged_minutes + 1, ticks + 1):
        try:
            ledger.debit(
                db,
                wallet,
                product.price_minor,
                reason=f"vpn_usage_{product.unit}",
                entity_type="usage_session",
                entity_id=session.id,
                idempotency_key=f"usage:session:{session.id}:tick:{n}",
            )
        except ledger.InsufficientFunds:
            _suspend(db, service, session)
            return charged
        session.charged_minutes = n
        session.cost_minor += product.price_minor
        charged += 1

    db.commit()
    if charged:
        log.info("session %s charged %s ticks, cost %s minor",
                 session.id, charged, charged * product.price_minor)
    return charged


def charge_active_sessions() -> None:
    db = SessionLocal()
    try:
        ids = db.execute(
            select(UsageSession.id).where(UsageSession.status == "active")
        ).scalars().all()
    finally:
        db.close()

    # Каждая сессия — в своей транзакции и сессии БД: сбой одной не откатывает остальные.
    for session_id in ids:
        db = SessionLocal()
        try:
            _charge_session(db, session_id)
        except Exception:
            db.rollback()
            log.exception("charge failed for session %s", session_id)
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
        db.commit()
        if stale:
            log.info("closed %s stale sessions", len(stale))
    finally:
        db.close()
