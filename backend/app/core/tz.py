from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3), name="MSK")


def now() -> datetime:
    """Единственный источник текущего времени для всего приложения (MSK)."""
    return datetime.now(MSK)


def as_msk(dt, fallback_tz=None):
    """Приводит datetime к MSK; наивные (старые) записи считаем UTC."""
    from datetime import timezone
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)
