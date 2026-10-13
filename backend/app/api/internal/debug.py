from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_internal_key
from app.models import ServiceInstance, UsageSession, VpnAccount, Wallet
from app.services import ledger

router = APIRouter(
    prefix="/internal/v1/debug",
    tags=["internal-debug"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/usage")
def debug_usage(db: Session = Depends(get_db)):
    """Показать состояние всех услуг и сессий — для диагностики списаний."""
    services = db.execute(select(ServiceInstance)).scalars().all()
    result = []
    for s in services:
        wallet = db.execute(select(Wallet).where(Wallet.user_id == s.user_id)).scalar_one_or_none()
        account = db.execute(
            select(VpnAccount).where(VpnAccount.service_instance_id == s.id)
        ).scalar_one_or_none()
        sessions = db.execute(
            select(UsageSession)
            .where(UsageSession.service_instance_id == s.id)
            .order_by(UsageSession.id.desc())
            .limit(3)
        ).scalars().all()
        result.append({
            "service_id": s.id,
            "user_id": s.user_id,
            "product_id": s.product_id,
            "status": s.status,
            "balance_minor": wallet.balance_minor if wallet else 0,
            "account": {
                "id": account.id if account else None,
                "username": account.username if account else None,
                "status": account.status if account else None,
            } if account else None,
            "recent_sessions": [
                {
                    "id": sess.id,
                    "status": sess.status,
                    "charged_minutes": sess.charged_minutes,
                    "cost_minor": sess.cost_minor,
                    "started_at": sess.started_at.isoformat() if sess.started_at else None,
                    "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
                }
                for sess in sessions
            ],
        })
    return JSONResponse(content=result)
