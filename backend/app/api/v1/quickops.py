import asyncio
import json
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.db import get_db
from app.deps import require_admin
from app.models import VpnNode
from app.services.tariffs import ensure_tariffs

router = APIRouter(prefix="/api/v1/admin", tags=["admin-quick"])


class NodeImport(BaseModel):
    inbound: dict | str
    inbound_id: int | None = None
    code: str | None = None
    name: str | None = None
    country: str = "NL"
    endpoint_host: str | None = None
    api_url: str | None = None
    api_user: str | None = None
    api_key: str | None = None
    api_token: str | None = None


class QuickTariffs(BaseModel):
    protocol: str = "vless"
    country: str = "NL"
    prices: dict = {}


@router.post("/nodes/import")
def node_import(
    payload: NodeImport,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Импорт VPN-ноды из JSON-конфига входящего подключения 3x-ui.
    Если inbound_id не указан — inbound создаётся в панели этим же конфигом."""
    from app.adapters.vpn.threexui import ThreeXuiAdapter

    inbound = payload.inbound
    if isinstance(inbound, str):
        inbound = json.loads(inbound)

    base = db.execute(
        select(VpnNode).where(VpnNode.api_kind == "3xui")
    ).scalars().first()
    api_url = payload.api_url or (base.api_url if base else None)
    api_user = payload.api_user or (base.api_user if base else None)
    api_key = payload.api_key or (
        security.decrypt_secret(base.api_key_enc) if base and base.api_key_enc else None
    )
    if not api_url or not api_user or not api_key:
        raise HTTPException(400, "No panel credentials: pass api_url/api_user/api_key")

    tmp = SimpleNamespace(
        id=0, api_url=api_url, api_user=api_user,
        api_key_enc=security.encrypt_secret(api_key),
        extra={"verify_tls": False},
    )
    adapter = ThreeXuiAdapter(tmp)

    inbound_id = payload.inbound_id
    if not inbound_id:
        data = asyncio.run(adapter._request("POST", "/panel/api/inbounds/add", inbound))
        inbound_id = (data.get("obj") or {}).get("id")
        if not inbound_id:
            lst = asyncio.run(adapter._request("GET", "/panel/api/inbounds/list"))
            for item in lst.get("obj") or []:
                if item.get("port") == inbound.get("port"):
                    inbound_id = item.get("id")
                    break
    if not inbound_id:
        raise HTTPException(502, "Panel did not return inbound id")

    rs = (inbound.get("streamSettings") or {}).get("realitySettings") or {}
    sni = (rs.get("serverNames") or [""])[0]
    pbk = (rs.get("settings") or {}).get("publicKey", "")
    fp = (rs.get("settings") or {}).get("fingerprint", "chrome")
    spx = (rs.get("settings") or {}).get("spiderX", "/")
    sid = (rs.get("shortIds") or [""])[0]
    port = inbound.get("port")
    protocol = inbound.get("protocol", "vless")

    code = payload.code or f"import-{port}"
    exists = db.execute(select(VpnNode).where(VpnNode.code == code)).scalar_one_or_none()
    if exists:
        raise HTTPException(409, f"Node {code} already exists")

    node = VpnNode(
        code=code,
        name=payload.name or f"{protocol.upper()} Reality {payload.country} ({port})",
        country=payload.country,
        protocol=protocol,
        api_kind="3xui",
        api_url=api_url,
        api_user=api_user,
        api_key_enc=security.encrypt_secret(api_key),
        endpoint_host=payload.endpoint_host or (base.endpoint_host if base else ""),
        endpoint_port=port,
        active=True,
        extra={"inbound_id": inbound_id, "sni": sni, "pbk": pbk, "sid": sid, "fp": fp, "spider_x": spx},
    )
    db.add(node)
    db.commit()
    return {"id": node.id, "code": node.code, "inbound_id": inbound_id, "extra": node.extra}


@router.post("/products/quick")
def products_quick(
    payload: QuickTariffs,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    created = ensure_tariffs(db, payload.protocol, payload.country, payload.prices or None)
    db.commit()
    return {"ok": True, "products": created}
