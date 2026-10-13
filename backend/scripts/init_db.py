from sqlalchemy import text

from app.db import engine
from app.models import Base

FK_CASCADE_FIXES = [
    "ALTER TABLE vpn_accounts DROP CONSTRAINT IF EXISTS vpn_accounts_service_instance_id_fkey",
    """ALTER TABLE vpn_accounts ADD CONSTRAINT vpn_accounts_service_instance_id_fkey
       FOREIGN KEY (service_instance_id) REFERENCES service_instances(id) ON DELETE CASCADE""",
    "ALTER TABLE usage_sessions DROP CONSTRAINT IF EXISTS usage_sessions_vpn_account_id_fkey",
    """ALTER TABLE usage_sessions ADD CONSTRAINT usage_sessions_vpn_account_id_fkey
       FOREIGN KEY (vpn_account_id) REFERENCES vpn_accounts(id) ON DELETE CASCADE""",
    "ALTER TABLE usage_sessions DROP CONSTRAINT IF EXISTS usage_sessions_service_instance_id_fkey",
    """ALTER TABLE usage_sessions ADD CONSTRAINT usage_sessions_service_instance_id_fkey
       FOREIGN KEY (service_instance_id) REFERENCES service_instances(id) ON DELETE CASCADE""",
]

CONSTRAINT_FIXES = [
    "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_type_ck",
    """ALTER TABLE products ADD CONSTRAINT products_type_ck
       CHECK (service_type IN ('vpn','vps','cctv','hosting','storage','mail'))""",
    "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unit_ck",
    """ALTER TABLE products ADD CONSTRAINT products_unit_ck
       CHECK (unit IN ('second','minute','hour','day','month','one_time'))""",
]


def main():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for sql in FK_CASCADE_FIXES + CONSTRAINT_FIXES:
            conn.execute(text(sql))
    print("Database tables created, constraints synced")


if __name__ == "__main__":
    main()
