from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.db import get_db
from app.deps import require_admin
from app.models import Product, ProvisioningTask, UsageSession, User, VpnNode
from app.schemas import (
    AdminCreditRequest, AdminNodeRequest, AdminProductRequest, UserOut,
)
from app.services import ledger

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.execute(select(User).order_by(User.id)).scalars().all()


@router.post("/wallets/{user_id}/credit")
def credit_wallet(
    user_id: int,
    body: AdminCreditRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = ledger.get_wallet(db, user_id)
    entry = ledger.credit(
        db,
        wallet,
        body.amount_minor,
        reason=body.reason,
        entity_type="manual_topup",
        entity_id=admin.id,
        idempotency_key=body.idempotency_key,
    )
    db.commit()
    return {"balance_minor": wallet.balance_minor, "ledger_entry_id": entry.id}


@router.post("/products", status_code=201)
def create_product(
    body: AdminProductRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    db.add(Product(**body.model_dump()))
    db.commit()
    return {"status": "created"}


@router.post("/nodes", status_code=201)
def create_node(
    body: AdminNodeRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    api_key = data.pop("api_key", None)
    ssh_key = data.pop("ssh_key", None)
    node = VpnNode(
        **data,
        api_key_enc=security.encrypt_secret(api_key) if api_key else None,
        ssh_key_enc=security.encrypt_secret(ssh_key) if ssh_key else None,
    )
    db.add(node)
    db.commit()
    return {"status": "created", "id": node.id}


@router.get("/provisioning/tasks")
def list_tasks(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.execute(select(ProvisioningTask).order_by(ProvisioningTask.id.desc()).limit(100)).scalars().all()


@router.get("/usage-sessions")
def list_sessions(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.execute(select(UsageSession).order_by(UsageSession.id.desc()).limit(100)).scalars().all()