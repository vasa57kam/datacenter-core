"""Системные настройки (key-value) для рантайм-конфига."""
from sqlalchemy import select

from app.models import SystemSetting


def get_setting(db, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row is not None else default


def set_setting(db, key: str, value: str) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()
