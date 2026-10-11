from sqlalchemy import inspect, text
from app.db import engine

def main():
    with engine.connect() as conn:
        # Проверяем существует ли таблица
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'payment_requests'
            );
        """)).scalar()
        
        if not result:
            print("ERROR: Table payment_requests does not exist!")
            print("Running migration...")
            conn.execute(text("""
                CREATE TABLE payment_requests (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id),
                    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
                    method TEXT NOT NULL,
                    comment TEXT,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    processed_at TIMESTAMPTZ
                );
                CREATE INDEX ix_payreq_user ON payment_requests(user_id);
            """))
            conn.commit()
            print("Table created successfully")
        else:
            print("Table payment_requests exists")
            
            # Проверяем колонки
            insp = inspect(engine)
            columns = [col['name'] for col in insp.get_columns('payment_requests')]
            print(f"Columns: {columns}")

if __name__ == "__main__":
    main()
