import asyncio
import logging
from datetime import timedelta
from time import time

from sqlalchemy import select

from app.adapters.vpn import get_adapter
from app.db import SessionLocal
from app.models import Product, ServiceInstance, VpnAccount, VpnNode
from app.services import ledger
from app.services.usage import TICK_SECONDS

log = logging.getLogger(__name__)

CAP = timedelta(days=7)
DRIFT_MS = 120_000  # дёргаем панель только если expiry уехал больше чем на 2 минуты


def _now_ms() -> int:
    return int(time() * 1000)


def sync_vless_limits() -> None:
    db = SessionLocal()
    try:
        accounts = db.execute(
            select(VpnAccount).where(
                VpnAccount.protocol == "vless",
                VpnAccount.status.in_(["active", "suspended"]),
            )
        ).scalars().all()

        for account in accounts:
            service = db.get(ServiceInstance, account.service_instance_id)
            node = db.get(VpnNode, account.node_id)
            if service is None or node is None or node.api_kind != "3xui":
                continue
            product = db.get(Product, service.product_id)
            if product is None or product.price_minor <= 0 or product.unit not in TICK_SECONDS:
                continue

            wallet = ledger.get_wallet(db, service.user_id)
            # сколько тиков оплачено; длительность тика зависит от единицы тарифа (сек/мин)
            prepaid_ticks = wallet.balance_minor // product.price_minor
            prepaid_minutes = prepaid_ticks * TICK_SECONDS[product.unit] // 60
            delta = min(timedelta(seconds=int(prepaid_ticks) * TICK_SECONDS[product.unit]), CAP)

            active = service.status == "active" and account.status == "active"
            if active:
                expiry_ms = _now_ms() + int(delta.total_seconds() * 1000)
            else:
                expiry_ms = _now_ms() - 1000

            extra = account.extra or {}
            last_expiry = extra.get("pushed_expiry")
            last_enable = extra.get("pushed_enable")
            if last_enable == active and (
                not active  # у выключенного клиента expiry «плывёт» вместе с now — сравниваем только флаг
                or (last_expiry is not None and abs(last_expiry - expiry_ms) < DRIFT_MS)
            ):
                continue  # ничего не изменилось — панель не трогаем

            adapter = get_adapter(node)
            try:
                asyncio.run(adapter.push_limits(account, expiry_ms, active))
                account.extra = {
                    **extra,
                    "pushed_expiry": expiry_ms,
                    "pushed_enable": active,
                    "limits_synced_at": _now_ms(),
                    "prepaid_minutes": int(prepaid_minutes),
                }
                db.commit()
            except Exception:
                db.rollback()
                log.exception("sync_vless_limits failed for account %s", account.id)
    finally:
        db.close()
