import argparse

from argon2 import PasswordHasher

from app.db import SessionLocal
from app.models import User, Wallet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    if db.query(User).filter(User.email == args.email).first():
        print("Admin already exists")
        return

    user = User(
        email=args.email,
        password_hash=PasswordHasher().hash(args.password),
        role="admin",
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id, currency="RUB", balance_minor=0))
    db.commit()
    print(f"Admin created: id={user.id}")


if __name__ == "__main__":
    main()