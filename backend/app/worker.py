from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.services import provisioning, sync, usage, usage_agent

scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job("interval", seconds=settings.charge_interval_seconds, coalesce=True, max_instances=1)
def charge_job():
    usage.charge_active_sessions()


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def stale_job():
    usage.close_stale_sessions()


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def usage_agent_job():
    usage_agent.poll_node_usage()


@scheduler.scheduled_job("interval", seconds=60, coalesce=True, max_instances=1)
def sync_job():
    sync.sync_vless_limits()


@scheduler.scheduled_job("interval", seconds=300, coalesce=True, max_instances=1)
def recover_job():
    provisioning.recover_stuck_tasks()


@scheduler.scheduled_job("interval", seconds=settings.provisioning_interval_seconds, coalesce=True, max_instances=1)
def provisioning_job():
    provisioning.process_pending_tasks_sync()


if __name__ == "__main__":
    print("billing worker started", flush=True)
    scheduler.start()
