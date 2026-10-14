import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.models import VpnNode


def import_node_from_inbound(
    db: Session,
    inbound: dict | str,
    inbound_id: int | None = None,
    code: str | None = None,
    name: str | None = None,
    country: str = "NL",
    endpoint_host: str | None = None,
    api_url: str | None = None,
    api_user: str | None = None,
    api_key: str | None = None,
    api_token: str | None = None,
) -> VpnNode:
    from app.adapters.vpn.threexui import ThreeXuiAdapter

    if isinstance(inbound, str):
        inbound = json.loads(inbound)

    base = db.execute(select(VpnNode).where(VpnNode.api_kind == "3xui")).scalars().first()

    auth_mode = None
    if api_token:
        auth_mode = "token"
        api_url = api_url or (base.api_url if base else None)
        api_user = api_user or "api-token"
        secret = api_token
    elif api_url:
        if not api_user or not api_key:
            raise ValueError("Для внешней панели укажите логин и пароль (или API-токен)")
        secret = api_key
    else:
        if base is None:
            raise ValueError("Нет ни одной ноды: укажите URL панели и реквизиты")
        api_url = base.api_url
        api_user = base.api_user
        secret = security.decrypt_secret(base.api_key_enc) if base.api_key_enc else None
        auth_mode = (base.extra or {}).get("auth_mode")
        if not secret:
            raise ValueError("У базовой ноды нет реквизитов панели")

    tmp = SimpleNamespace(
        id=0, api_url=api_url, api_user=api_user,
        api_key_enc=security.encrypt_secret(secret),
        extra={"verify_tls": False, **({"auth_mode": "token"} if auth_mode == "token" else {})},
    )
    adapter = ThreeXuiAdapter(tmp)

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
        raise ValueError("Панель не вернула id inbound")

    rs = (inbound.get("streamSettings") or {}).get("realitySettings") or {}
    sni = (rs.get("serverNames") or [""])[0]
    pbk = (rs.get("settings") or {}).get("publicKey", "")
    fp = (rs.get("settings") or {}).get("fingerprint", "chrome")
    spx = (rs.get("settings") or {}).get("spiderX", "/")
    sid = (rs.get("shortIds") or [""])[0]
    port = inbound.get("port")
    protocol = inbound.get("protocol", "vless")

    code = code or f"import-{port}"
    if db.execute(select(VpnNode).where(VpnNode.code == code)).scalar_one_or_none():
        raise ValueError(f"Нода {code} уже существует")

    node = VpnNode(
        code=code,
        name=name or f"{protocol.upper()} Reality {country} ({port})",
        country=country,
        protocol=protocol,
        api_kind="3xui",
        api_url=api_url,
        api_user=api_user,
        api_key_enc=security.encrypt_secret(secret),
        endpoint_host=endpoint_host or (base.endpoint_host if base else ""),
        endpoint_port=port,
        active=True,
        extra={
            "inbound_id": inbound_id, "sni": sni, "pbk": pbk, "sid": sid,
            "fp": fp, "spider_x": spx,
            **({"auth_mode": "token"} if auth_mode == "token" else {}),
        },
    )
    db.add(node)
    db.flush()
    return node
