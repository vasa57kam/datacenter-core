"""Дивиденды: начисление доли дохода владельцу и партнёрам-инвесторам."""
from __future__ import annotations
import logging
from datetime import timedelta
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, select
from sqlalchemy.orm import Session

from app.core.tz import now as tz_now
from app.core.settings_svc import get_setting
from app.db import Base, SessionLocal, engine
from app.services import ledger

log = logging.getLogger(__name__)

class PartnerShare(Base):
    __tablename__ = "partner_shares"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)      # None = внешний инвестор
    title = Column(String, default="")
    invested_minor = Column(BigInteger, default=0)
    share_percent = Column(Integer, default=0)    # доля пула, %
    status = Column(String, default="active")
    created_at = Column(DateTime, default=tz_now)

class DividendAccrual(Base):
    __tablename__ = "dividend_accruals"
    id = Column(Integer, primary_key=True)
    partner_id = Column(Integer)
    period = Column(String)
    revenue_minor = Column(BigInteger, default=0)
    pool_minor = Column(BigInteger, default=0)
    amount_minor = Column(BigInteger, default=0)
    idem = Column(String, unique=True)

class PayoutRequest(Base):
    __tablename__ = "payout_requests"
    id = Column(Integer, primary_key=True)
    partner_id = Column(Integer)
    amount_minor = Column(BigInteger, default=0)
    requisites = Column(String, default="")
    status = Column(String, default="pending")    # pending/paid/rejected
    created_at = Column(DateTime, default=tz_now)
    paid_at = Column(DateTime, nullable=True)

def ensure_tables() -> None:
    Base.metadata.create_all(bind=engine)   # создаёт только отсутствующие таблицы

def revenue_for(db: Session, start, end) -> int:
    from app.models import LedgerEntry
    q = select(LedgerEntry.amount_minor).where(
        LedgerEntry.created_at >= start, LedgerEntry.created_at < end,
        LedgerEntry.amount_minor < 0,
        LedgerEntry.reason.like("vpn_usage_%"))
    rev = -sum(r[0] or 0 for r in db.execute(q).all())
    q2 = select(LedgerEntry.amount_minor).where(
        LedgerEntry.created_at >= start, LedgerEntry.created_at < end,
        LedgerEntry.amount_minor < 0,
        LedgerEntry.reason.like("service_activation_%"))
    return rev - sum(r[0] or 0 for r in db.execute(q2).all())

def accrue_yesterday() -> int:
    db = SessionLocal()
    try:
        ensure_tables()
        today = tz_now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=1)
        period = start.strftime("%Y-%m-%d")
        if db.execute(select(DividendAccrual).where(DividendAccrual.period == period)).scalars().first():
            return 0
        pool_pct = int(get_setting(db, "dividend_pool_percent", "30") or 0)
        if pool_pct <= 0:
            return 0
        revenue = revenue_for(db, start, today)
        pool = revenue * pool_pct // 100
        partners = db.execute(select(PartnerShare).where(PartnerShare.status == "active")).scalars().all()
        total = sum(p.share_percent or 0 for p in partners)
        if pool <= 0 or not partners or total <= 0:
            return 0
        for p in partners:
            amount = pool * (p.share_percent or 0) // total
            if amount <= 0:
                continue
            db.add(DividendAccrual(partner_id=p.id, period=period, revenue_minor=revenue,
                                   pool_minor=pool, amount_minor=amount,
                                   idem=f"div:{period}:{p.id}"))
            if p.user_id:
                from app.models import User
                u = db.get(User, p.user_id)
                if u is not None:
                    w = ledger.get_wallet(db, u.id)
                    ledger.credit(db, w, amount, reason="dividend_accrual",
                                  entity_type="partner", entity_id=p.id,
                                  idempotency_key=f"div:{period}:{p.id}")
        db.commit()
        log.info("dividends %s: revenue=%s pool=%s partners=%s", period, revenue, pool, len(partners))
        return pool
    finally:
        db.close()
