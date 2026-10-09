from sqlalchemy import text

from app.db import engine
from app.models import Base

CONSTRAINT_FIXES = [
    """ALTER TABLE products DROP CONSTRAINT IF EXISTS products_type_ck""",
    """ALTER TABLE products ADD CONSTRAINT products_type_ck
       CHECK (service_type IN ('vpn','vps','cctv','hosting','storage','mail'))""",
    """ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unit_ck""",
    """ALTER TABLE products ADD CONSTRAINT products_unit_ck
       CHECK (unit IN ('minute','month','one_time'))""",
]


def main():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for sql in CONSTRAINT_FIXES:
            conn.execute(text(sql))
    print("Database tables created, constraints synced")


if __name__ == "__main__":
    main()
