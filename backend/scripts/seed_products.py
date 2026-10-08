from app.db import SessionLocal
from app.models import Product

PRODUCTS = [
    {"code": "vpn-vless-minute", "service_type": "vpn", "name": "VLESS Reality (NL), поминутно",
     "unit": "minute", "price_minor": 150, "config": {"protocol": "vless"}},
    {"code": "vpn-wireguard-minute", "service_type": "vpn", "name": "WireGuard (RU), поминутно",
     "unit": "minute", "price_minor": 100, "config": {"protocol": "wireguard"}},
    {"code": "vpn-openvpn-minute", "service_type": "vpn", "name": "OpenVPN (RU), поминутно",
     "unit": "minute", "price_minor": 100, "active": False, "config": {"protocol": "openvpn"}},
    {"code": "cctv-camera-month", "service_type": "cctv", "name": "Камера CCTV Cloud, месяц",
     "unit": "month", "price_minor": 50000, "active": False, "config": {"integration": "cctv-cloud"}},
]


def main():
    db = SessionLocal()
    for item in PRODUCTS:
        if not db.query(Product).filter(Product.code == item["code"]).first():
            db.add(Product(**item))
    db.commit()
    print("Products seeded")


if __name__ == "__main__":
    main()