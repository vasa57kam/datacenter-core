"""Офлайн-гарант: срок 'действует до' в панели + сверка после простоя."""
import asyncio
import concurrent.futures
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.vpn import get_adapter
from app.core.notifications import notify_admin
from app.core.settings_svc import get_setting, set_setting
from app.core.tz import now as tz_now
from app.db import SessionLocal
from app.models import Product, ServiceInstance, VpnAccount, VpnNode
from app.services import ledger

log = logging.getLogger(__name__)
_last = {"t": 0.0}
INTERVAL = 600


def throttled_guard() -> None:
    if time.time() - _last["t"] < INTERVAL:
        return
    _last["t"] = time.time()
    try:
        run_guard()
    except Exception:
        log.exception("offline guard crashed")


def _run(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=20)


def run_guard(db=None) -> None:
    own = db is None
    if own:
        db = SessionLocal()
    try:
        if get_setting(db, "offline_mode", "1") != "1":
            return
        cap_hours = int(get_setting(db, "offline_cap_hours", "72"))
        now = tz_now()
        outage_start = None
        last_run_s = get_setting(db, "guard_last_run", "")
        if last_run_s:
            try:
                lr = datetime.fromisoformat(last_run_s)
                if lr.tzinfo is None:
                    lr = lr.replace(tzinfo=now.tzinfo)
                if now - lr > timedelta(minutes=15):
                    outage_start = lr
            except ValueError:
                pass
        set_setting(db, "guard_last_run", now.isoformat())
        services = db.execute(select(ServiceInstance).where(ServiceInstance.status == "active")).scalars().all()
        for sv in services:
            try:
                _process(db, sv, now, cap_hours, outage_start)
            except Exception:
                log.exception("guard: service %s failed", sv.id)
        db.commit()
    finally:
        if own:
            db.close()


def _process(db, sv, now, cap_hours, outage_start) -> None:
    product = db.get(Product, sv.product_id)
    if product is None or product.unit not in ("second", "minute", "month"):
        return
    account = db.execute(select(VpnAccount).where(VpnAccount.service_instance_id == sv.id, VpnAccount.status != "deleted")).scalar_one_or_none()
    if account is None:
        return
    node = db.get(VpnNode, account.node_id)
    if node is None:
        return
    adapter = get_adapter(node)
    cfg = dict(sv.config or {})
    wallet = ledger.get_wallet(db, sv.user_id)
    traffic = _run(adapter.get_client_traffic(db, account))
    bytes_now = traffic["bytes"] if traffic else None

    if product.unit == "month":
        period_end = cfg.get("period_end")
        expiry = datetime.fromisoformat(period_end) if period_end else now + timedelta(days=30)
        if period_end is None:
            cfg["period_end"] = expiry.isoformat()
        granted_sec = 0
    else:
        tick = 1 if product.unit == "second" else 60
        afford = max(0, wallet.balance_minor + (getattr(wallet, "promise_limit_minor", 0) or 0)) // max(1, product.price_minor)
        horizon_sec = min(afford * tick, cap_hours * 3600)
        expiry = now + timedelta(seconds=horizon_sec)
        granted_sec = horizon_sec

    snap = cfg.get("traffic_snap")
    if outage_start is not None and snap is not None and bytes_now is not None and bytes_now > snap:
        tick = 1 if product.unit == "second" else 60
        window_sec = int((now - outage_start).total_seconds())
        charge_sec = min(window_sec, cfg.get("granted_sec") or window_sec)
        ticks_due = charge_sec // tick
        base = int(outage_start.timestamp())
        charged = 0
        for n in range(1, ticks_due + 1):
            try:
                ledger.debit(db, wallet, product.price_minor, reason=f"vpn_usage_{product.unit}",
                             entity_type="service_instance", entity_id=sv.id,
                             idempotency_key=f"reconcile:{sv.id}:{base}:{n}")
            except ledger.InsufficientFunds:
                break
            charged += 1
        if charged:
            rub = charged * product.price_minor / 100
            notify_admin(db, f"⚡ Сверка после сбоя: услуга #{sv.id} ({sv.name}) — списано {rub:.2f} ₽ за время простоя биллинга")

    pushed = cfg.get("pushed_expiry")
    drift = None
    if pushed:
        try:
            drift = abs((expiry - datetime.fromisoformat(pushed)).total_seconds())
        except ValueError:
            drift = None
    if drift is None or drift > 900:
        if _run(adapter.set_client_expiry(db, account, node, int(expiry.timestamp() * 1000))):
            cfg["pushed_expiry"] = expiry.isoformat()
            cfg["granted_sec"] = granted_sec
            log.info("guard: service %s expiry pushed until %s", sv.id, expiry.isoformat())

    if bytes_now is not None:
        cfg["traffic_snap"] = bytes_now
    sv.config = cfg
    flag_modified(sv, "config")
