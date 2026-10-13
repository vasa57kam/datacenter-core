from sqlalchemy import text

from app.db import engine
from app.models import Base

CONSTRAINT_FIXES = [
    "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_type_ck",
    """ALTER TABLE products ADD CONSTRAINT products_type_ck
       CHECK (service_type IN ('vpn','vps','cctv','hosting','storage','mail'))""",
    "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unit_ck",
    """ALTER TABLE products ADD CONSTRAINT products_unit_ck
       CHECK (unit IN ('second','minute','hour','day','month','one_time'))""",
    # Дубли активных сессий (если уже появились) закрываем, оставляя самую новую,
    # иначе уникальный индекс ниже не создастся.
    """UPDATE usage_sessions u SET status='closed', ended_at=COALESCE(u.ended_at, now())
       WHERE u.status='active' AND EXISTS (
         SELECT 1 FROM usage_sessions n
         WHERE n.vpn_account_id=u.vpn_account_id AND n.status='active' AND n.id>u.id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_one_active_per_account
       ON usage_sessions (vpn_account_id) WHERE status = 'active'""",
]


def main():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for sql in CONSTRAINT_FIXES:
            conn.execute(text(sql))
    print("Database tables created, constraints synced")


if __name__ == "__main__":
    main()
