"""Background worker: provisioning, usage billing, sync, recovery."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.services import dividends, provisioning, sync, usage, usage_agent

log = logging.getLogger(__name__)

# Отдельный пул для async-задач usage_agent (чтобы не блокировать scheduler)
_usage_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="usage")


def _run_usage_agent() -> None:
    """Обёртка: запускаем asyncio.run в отдельном потоке."""
    import asyncio
    try:
        asyncio.run(usage_agent.poll_node_usage_async())
    except Exception:
        log.exception("usage agent job failed")


scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job("interval", seconds=settings.charge_interval_seconds, coalesce=True, max_instances=1)
def charge_job():
    usage.charge_active_sessions()


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def stale_job():
    usage.close_stale_sessions()


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def usage_agent_job():
    _usage_pool.submit(_run_usage_agent)


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def sync_job():
    sync.sync_vless_limits()


@scheduler.scheduled_job("interval", seconds=300, coalesce=True, max_instances=1)
def recover_job():
    provisioning.recover_stuck_tasks()


@scheduler.scheduled_job("interval", seconds=settings.provisioning_interval_seconds, coalesce=True, max_instances=1)
def provisioning_job():
    provisioning.process_pending_tasks_sync()

@scheduler.scheduled_job("cron", hour=0, minute=5, coalesce=True, max_instances=1)
def dividend_job():
    from app.services import dividends
    dividends.accrue_yesterday()


if __name__ == "__main__":
    log.info("billing worker started")
    scheduler.start()
