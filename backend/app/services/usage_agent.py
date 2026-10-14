"""Usage agent: polls 3x-ui panels for online clients and reports traffic."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy import select

from app.adapters.vpn import get_adapter
from app.db import SessionLocal
from app.models import VpnAccount, VpnNode
from app.services import usage

log = logging.getLogger(__name__)


async def _poll_node(node: VpnNode) -> None:
    """Poll one node: create/update sessions for online clients."""
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
                try:
                    tr = await adapter.fetch_traffic(acc.username)
                    rx = int(tr.get("up") or 0)
                    tx = int(tr.get("down") or 0)
                except Exception:
                    log.exception("usage agent: traffic fetch failed for %s", acc.username)
            item = SimpleNamespace(
                vpn_account_id=acc.id,
                active=bool(online and acc.status == "active"),
                rx_bytes=rx,
                tx_bytes=tx,
                external_session_id=None,
            )
            usage.report_usage(db, node, item)
        db.commit()
        log.info(
            "usage agent: node %s accounts=%s online=%s",
            node.code, len(accounts), len(onlines),
        )
    except Exception:
        db.rollback()
        log.exception("usage agent: node %s failed", node.code)
    finally:
        db.close()


def poll_node_usage() -> None:
    """Entry point for the scheduler. Runs async polling on the existing event loop."""
    import asyncio

    db = SessionLocal()
    try:
        nodes = db.execute(
            select(VpnNode).where(
                VpnNode.active.is_(True),
                VpnNode.api_kind == "3xui",
            )
        ).scalars().all()
    finally:
        db.close()

    if not nodes:
        return

    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Мы внутри apscheduler — создаём задачу, но не ждём (fire-and-forget)
        # Чтобы не блокировать scheduler, используем run_coroutine_threadsafe
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            for node in nodes:
                pool.submit(asyncio.run, _poll_node(node))
    else:
        for node in nodes:
            loop.run_until_complete(_poll_node(node))


async def poll_node_usage_async() -> None:
    """Async entry point: polls all active 3x-ui nodes."""
    db = SessionLocal()
    try:
        nodes = db.execute(
            select(VpnNode).where(
                VpnNode.active.is_(True),
                VpnNode.api_kind == "3xui",
            )
        ).scalars().all()
    finally:
        db.close()
    for node in nodes:
        try:
            await _poll_node(node)
        except Exception:
            log.exception("usage agent: node %s failed", node.code)
