import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.services import provisioning, sync, usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

scheduler = BlockingScheduler(
    timezone="UTC",
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
)


@scheduler.scheduled_job("interval", seconds=settings.charge_interval_seconds)
def charge_job():
    usage.charge_active_sessions()


@scheduler.scheduled_job("interval", seconds=60)
def stale_job():
    usage.close_stale_sessions()


@scheduler.scheduled_job("interval", seconds=60)
def sync_job():
    sync.sync_vless_limits()


@scheduler.scheduled_job("interval", seconds=300)
def recover_job():
    provisioning.recover_stuck_tasks()


@scheduler.scheduled_job("interval", seconds=settings.provisioning_interval_seconds)
def provisioning_job():
    provisioning.process_pending_tasks_sync()


if __name__ == "__main__":
    print("billing worker started")
    scheduler.start()
