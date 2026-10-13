import asyncio
import logging
from types import SimpleNamespace

from sqlalchemy import select

from app.adapters.vpn import get_adapter
from app.db import SessionLocal
from app.models import VpnAccount, VpnNode
from app.services import usage

log = logging.getLogger(__name__)


async def _poll_node(node: VpnNode) -> None:
    db = SessionLocal()
    try:
        adapter = get_adapter(node)
        onlines = set(await adapter.fetch_onlines())
        accounts = db.execute(
            select(VpnAccount).where(
                VpnAccount.node_id == node.id,
                VpnAccount.status.in_(("active", "suspended")),
            )
        ).scalars().all()
        for acc in accounts:
            online = acc.username in onlines
            rx = tx = 0
            if online:
                tr = await adapter.fetch_traffic(acc.username)
                rx = int(tr.get("up") or 0)
                tx = int(tr.get("down") or 0)
            item = SimpleNamespace(
                vpn_account_id=acc.id,
                active=online and acc.status == "active",
                rx_bytes=rx,
                tx_bytes=tx,
                external_session_id=None,
            )
            usage.report_usage(db, node, item)
        db.commit()
        log.info("usage agent: node %s accounts=%s online=%s", node.code, len(accounts), len(onlines))
    except Exception:
        db.rollback()
        log.exception("usage agent: node %s failed", node.code)
    finally:
        db.close()


def poll_node_usage() -> None:
    db = SessionLocal()
    try:
        nodes = db.execute(
            select(VpnNode).where(VpnNode.active.is_(True), VpnNode.api_kind == "3xui")
        ).scalars().all()
    finally:
        db.close()
    for node in nodes:
        asyncio.run(_poll_node(node))
