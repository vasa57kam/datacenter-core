from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import LedgerEntry, User
from app.schemas import LedgerOut, WalletOut
from app.services import ledger

router = APIRouter(prefix="/api/v1/wallet", tags=["wallet"])


@router.get("", response_model=WalletOut)
def get_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ledger.get_wallet(db, user.id)


@router.get("/ledger", response_model=list[LedgerOut])
def get_ledger(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wallet = ledger.get_wallet(db, user.id)
    entries = db.execute(
        select(LedgerEntry)
        .where(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.id.desc())
        .limit(limit)
    ).scalars().all()
    return entries