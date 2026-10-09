from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.db import get_db
from app.deps import require_internal_key
from app.models import (
    ExternalIdentity, Product, ServiceInstance, User,
)
from app.schemas.internal import (
    CctvChargeRequest, CctvCreditRequest, CctvOrderRequest, CctvUserEnsureRequest,
)
from app.services import ledger

router = APIRouter(prefix="/internal/v1/cctv", tags=["internal"])


def _find_user(db: Session, username: str | None, email: str | None):
    if email:
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is not None:
            return u
    if username:
        ident = db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "cctv",
                ExternalIdentity.external_id == username,
            )
        ).scalar_one_or_none()
        if ident is not None:
            return db.get(User, ident.user_id)
    return None


def _ensure_user(db: Session, username: str, email: str | None):
    user = _find_user(db, username, email)
    if user is not None:
        return user, False
    mail = email or f"cctv-{username}@users.itkam34.local"
    user = User(
        email=mail,
        password_hash=security.hash_password(security.new_uuid()),
        role="client",
    )
    db.add(user)
    db.flush()
    db.add(ledger.get_wallet(db, user.id))
    db.add(ExternalIdentity(provider="cctv", external_id=username, user_id=user.id))
    db.flush()
    return user, True


@router.post("/users/ensure")
def cctv_user_ensure(
    body: CctvUserEnsureRequest,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    user, created = _ensure_user(db, body.cctv_username, body.email)
    db.commit()
    return {"user_id": user.id, "created": created}


@router.post("/orders", status_code=202)
def cctv_order(
    body: CctvOrderRequest,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    user = _find_user(db, body.cctv_username, body.user_email)
    if user is None:
        if body.cctv_username:
            user, _ = _ensure_user(db, body.cctv_username, None)
        else:
            raise HTTPException(status_code=404, detail="User not found")
    product = db.execute(
        select(Product).where(Product.code == "cctv-camera-month")
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product cctv-camera-month not found")

    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=f"CCTV camera {body.camera_id}",
        status="pending",
        config={
            "camera_id": body.camera_id,
            "months": body.months,
            "price_minor": body.price_minor,
            "idempotency_key": body.idempotency_key,
        },
    )
    db.add(service)
    db.commit()
    return {"status": "accepted", "service_instance_id": service.id, "user_id": user.id}


@router.post("/charges")
def cctv_charge(
    body: CctvChargeRequest,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    user = db.get(User, body.user_id) if body.user_id else _find_user(db, body.cctv_username, None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = ledger.get_wallet(db, user.id)
    try:
        entry = ledger.debit(
            db, wallet, body.amount_minor,
            reason=body.reason,
            entity_type="cctv_charge",
            entity_id=user.id,
            idempotency_key=body.idempotency_key,
        )
    except ledger.InsufficientFunds:
        db.rollback()
        return {"ok": False, "code": "insufficient_funds", "balance_minor": wallet.balance_minor}
    db.commit()
    return {"ok": True, "ledger_entry_id": entry.id, "balance_minor": wallet.balance_minor}


@router.post("/credits")
def cctv_credit(
    body: CctvCreditRequest,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    user = db.get(User, body.user_id) if body.user_id else _find_user(db, body.cctv_username, None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = ledger.get_wallet(db, user.id)
    entry = ledger.credit(
        db, wallet, body.amount_minor,
        reason=body.reason,
        entity_type="cctv_credit",
        entity_id=user.id,
        idempotency_key=body.idempotency_key,
    )
    db.commit()
    return {"ok": True, "ledger_entry_id": entry.id, "balance_minor": wallet.balance_minor}


@router.get("/users/{cctv_username}/state")
def cctv_user_state(
    cctv_username: str,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    user = _find_user(db, cctv_username, None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = ledger.get_wallet(db, user.id)
    services = db.execute(
        select(ServiceInstance).where(ServiceInstance.user_id == user.id)
    ).scalars().all()
    return {
        "user_id": user.id,
        "balance_minor": wallet.balance_minor,
        "services": [
            {"id": s.id, "name": s.name, "status": s.status, "config": s.config}
            for s in services
        ],
    }
