from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3), name="MSK")


def now() -> datetime:
    """Единственный источник текущего времени для всего приложения (MSK)."""
    return datetime.now(MSK)
