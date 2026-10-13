import argparse
import json

from app.db import SessionLocal
from app.services.tariffs import ensure_tariffs


def main():
    ap = argparse.ArgumentParser(description="Quick tariff generator")
    ap.add_argument("--protocol", default="vless")
    ap.add_argument("--country", default="NL")
    ap.add_argument("--prices", default="", help='JSON: {"minute":150,"second":2,"gb":100,"month":30000}')
    a = ap.parse_args()
    prices = json.loads(a.prices) if a.prices else None
    db = SessionLocal()
    try:
        for row in ensure_tariffs(db, a.protocol, a.country, prices):
            print(row)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
