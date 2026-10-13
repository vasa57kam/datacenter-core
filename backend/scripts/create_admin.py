import argparse

from sqlalchemy import select

from app.core import security
from app.db import SessionLocal
from app.models import User


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    a = ap.parse_args()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == a.email)).scalar_one_or_none()
        if user is None:
            user = User(
                email=a.email,
                role="admin",
                status="active",
                password_hash=security.hash_password(a.password),
            )
            db.add(user)
        else:
            user.role = "admin"
            user.status = "active"
            user.password_hash = security.hash_password(a.password)
        db.commit()
        print("admin ready:", a.email)
    finally:
        db.close()


if __name__ == "__main__":
    main()
