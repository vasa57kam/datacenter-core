from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LedgerEntry, Wallet


class InsufficientFunds(Exception):
    pass


class IdempotencyConflict(Exception):
    """idempotency_key уже использован для другой операции (другой кошелёк/сумма)."""


def get_wallet(db: Session, user_id: int) -> Wallet:
    wallet = db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one_or_none()
    if wallet is None:
        try:
            with db.begin_nested():
                wallet = Wallet(user_id=user_id, currency="RUB", balance_minor=0)
                db.add(wallet)
                db.flush()
        except IntegrityError:  # параллельный запрос успел создать кошелёк
            wallet = db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one()
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
    if amount_minor == 0:
        raise ValueError("amount_minor must be non-zero")

    # Сначала блокируем кошелёк, и только потом проверяем ключ идемпотентности —
    # иначе два параллельных запроса с одним ключом оба проходят проверку.
    # populate_existing: без него SQLAlchemy вернёт уже загруженный объект с
    # устаревшим balance_minor, и блокировка не защитит от потери обновления.
    wallet = db.execute(
        select(Wallet)
        .where(Wallet.id == wallet_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()

    existing = db.execute(
        select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.wallet_id != wallet_id or existing.amount_minor != amount_minor:
            raise IdempotencyConflict(f"idempotency_key {idempotency_key!r} already used")
        return existing

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
