from sqlalchemy import text
from app.db import engine

def main():
    with engine.begin() as conn:
        # Добавляем CASCADE для UsageSession
        conn.execute(text("""
            ALTER TABLE usage_sessions 
            DROP CONSTRAINT IF EXISTS usage_sessions_vpn_account_id_fkey
        """))
        conn.execute(text("""
            ALTER TABLE usage_sessions 
            ADD CONSTRAINT usage_sessions_vpn_account_id_fkey 
            FOREIGN KEY (vpn_account_id) REFERENCES vpn_accounts(id) ON DELETE CASCADE
        """))
        
        conn.execute(text("""
            ALTER TABLE usage_sessions 
            DROP CONSTRAINT IF EXISTS usage_sessions_service_instance_id_fkey
        """))
        conn.execute(text("""
            ALTER TABLE usage_sessions 
            ADD CONSTRAINT usage_sessions_service_instance_id_fkey 
            FOREIGN KEY (service_instance_id) REFERENCES service_instances(id) ON DELETE CASCADE
        """))
        
        # VpnAccount уже имеет CASCADE (из модели)
        print("CASCADE constraints added for usage_sessions")

if __name__ == "__main__":
    main()
