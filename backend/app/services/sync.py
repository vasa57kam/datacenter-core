import asyncio
from datetime import timedelta
from time import time

from sqlalchemy import select

from app.adapters.vpn import get_adapter
from app.db import SessionLocal
from app.models import Product, ServiceInstance, VpnAccount, VpnNode
from app.services import ledger

CAP = timedelta(days=7)


def _now_ms() -> int:
    return int(time() * 1000)


def sync_vless_limits() -> None:
    """Пушит в 3x-ui оплаченный конверт минут: панель сама гасит клиента,
    даже если биллинг лежит. После возвращения биллинга конверт пересчитывается."""
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
            if product is None or product.price_minor <= 0:
                continue

            wallet = ledger.get_wallet(db, service.user_id)
            prepaid_minutes = wallet.balance_minor // product.price_minor
            delta = min(timedelta(minutes=int(prepaid_minutes)), CAP)

            if service.status == "active" and account.status == "active":
                expiry_ms = _now_ms() + int(delta.total_seconds() * 1000)
                enable = True
            else:
                expiry_ms = _now_ms() - 1000
                enable = False

            adapter = get_adapter(node)
            try:
                asyncio.run(adapter.push_limits(account, expiry_ms, enable))
                account.extra = {
                    **(account.extra or {}),
                    "limits_synced_at": _now_ms(),
                    "prepaid_minutes": int(prepaid_minutes),
                }
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()
