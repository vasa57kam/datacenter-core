from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.services import provisioning, usage

scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job("interval", seconds=settings.charge_interval_seconds)
def charge_job():
    usage.charge_active_sessions()


@scheduler.scheduled_job("interval", seconds=60)
def stale_job():
    usage.close_stale_sessions()


@scheduler.scheduled_job("interval", seconds=settings.provisioning_interval_seconds)
def provisioning_job():
    provisioning.process_pending_tasks_sync()


if __name__ == "__main__":
    print("billing worker started")
    scheduler.start()