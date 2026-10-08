from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_internal_key
from app.models import VpnNode
from app.schemas import VpnUsagePayload
from app.services import usage

router = APIRouter(prefix="/internal/v1/vpn", tags=["internal"])


@router.post("/usage")
def vpn_usage(
    payload: VpnUsagePayload,
    _: None = Depends(require_internal_key),
    db: Session = Depends(get_db),
):
    node = db.execute(
        select(VpnNode).where(VpnNode.code == payload.node_code, VpnNode.active.is_(True))
    ).scalar_one_or_none()
    if node is None:
        return {"ok": False, "error": "unknown node"}

    processed = 0
    for item in payload.sessions:
        if usage.report_usage(db, node, item) is not None:
            processed += 1
    db.commit()
    return {"ok": True, "processed": processed}