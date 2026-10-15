from sqlalchemy import select

from app.models import Product

UNITS = [
    ("second", "посекундно", 2),
    ("minute", "поминутно", 150),
    ("gb", "за трафик, ₽ за ГиБ", 100),
    ("month", "помесячно", 30000),
]


def ensure_tariffs(db, protocol: str, country: str, prices: dict | None = None) -> list[dict]:
    """Создаёт или обновляет стандартный набор тарифов протокола. Идемпотентно."""
    prices = prices or {}
    out = []
    for unit, label, default_price in UNITS:
        price = int(prices.get(unit, default_price))
        code = f"vpn-{protocol}-{unit}"
        name = f"Защищённый канал {country}, {label}"
        product = db.execute(
            select(Product).where(Product.code == code)
        ).scalar_one_or_none()
        if product is None:
            product = Product(
                code=code, service_type="vpn", name=name, unit=unit,
                price_minor=price, active=True, config={"protocol": protocol},
            )
            db.add(product)
            out.append({"code": code, "created": True, "price_minor": price})
        else:
            product.price_minor = price
            product.name = name
            product.unit = unit
            product.active = True
            product.config = {"protocol": protocol}
            out.append({"code": code, "created": False, "price_minor": price})
    db.flush()
    return out
