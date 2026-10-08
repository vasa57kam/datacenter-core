from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, Wallet


class InsufficientFunds(Exception):
    pass


def get_wallet(db: Session, user_id: int) -> Wallet:
    wallet = db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(user_id=user_id, currency="RUB", balance_minor=0)
        db.add(wallet)
        db.flush()
    return wallet


def post_entry(
    db: Session,
    *,
    wallet_id: int,
    amount_minor: int,
    reason: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    idempotency_key: str,
    meta: dict | None = None,
) -> LedgerEntry:
    existing = db.execute(
        select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    wallet = db.execute(
        select(Wallet).where(Wallet.id == wallet_id).with_for_update()
    ).scalar_one()

    new_balance = wallet.balance_minor + amount_minor
    if new_balance < 0:
        raise InsufficientFunds(f"wallet {wallet_id} balance would go negative")

    entry = LedgerEntry(
        wallet_id=wallet_id,
        amount_minor=amount_minor,
        balance_after_minor=new_balance,
        entry_type="credit" if amount_minor >= 0 else "debit",
        reason=reason,
        entity_type=entity_type,
        entity_id=entity_id,
        idempotency_key=idempotency_key,
        meta=meta or {},
    )
    wallet.balance_minor = new_balance
    wallet.version += 1
    db.add(entry)
    db.flush()
    return entry


def credit(db, wallet: Wallet, amount_minor: int, **kw) -> LedgerEntry:
    return post_entry(db, wallet_id=wallet.id, amount_minor=amount_minor, **kw)


def debit(db, wallet: Wallet, amount_minor: int, **kw) -> LedgerEntry:
    return post_entry(db, wallet_id=wallet.id, amount_minor=-amount_minor, **kw)