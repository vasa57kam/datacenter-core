import json
import re
import time

import httpx

from app.adapters.vpn.base import VpnAdapter
from app.core import security

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 billing-core/1.0"}
CSRF_RE = re.compile(
    r'name="csrf-token"\s+content="([^"]+)"|content="([^"]+)"\s+name="csrf-token"'
)

_AUTH_CACHE: dict[int, dict] = {}
_AUTH_TTL = 600


class ThreeXuiAdapter(VpnAdapter):
    def _base(self) -> str:
        return self.node.api_url.rstrip("/")

    def _password(self) -> str:
        return security.decrypt_secret(self.node.api_key_enc)

    def _client(self, cookies: dict | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            verify=self.node.extra.get("verify_tls", False),
            headers=UA,
            follow_redirects=True,
            cookies=cookies or {},
        )

    async def _login_fresh(self) -> tuple[dict, str]:
        async with self._client() as client:
            page = await client.get(f"{self._base()}/panel/")
            csrf = ""
            m = CSRF_RE.search(page.text or "")
            if m:
                csrf = m.group(1) or m.group(2) or ""
            headers = {"Referer": f"{self._base()}/panel/", "X-CSRF-Token": csrf}
            resp = await client.post(
                f"{self._base()}/login",
                json={"username": self.node.api_user, "password": self._password()},
                headers=headers,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"3x-ui login failed: HTTP {resp.status_code}")
            return {k: v for k, v in client.cookies.items()}, csrf

    async def _auth(self) -> tuple[dict, str]:
        now = time.time()
        cached = _AUTH_CACHE.get(self.node.id)
        if cached and now - cached["ts"] < _AUTH_TTL:
            return cached["cookies"], cached["csrf"]
        cookies, csrf = await self._login_fresh()
        _AUTH_CACHE[self.node.id] = {"cookies": cookies, "csrf": csrf, "ts": now}
        return cookies, csrf

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        cookies, csrf = await self._auth()
        async with self._client(cookies) as client:
            resp = await client.request(
                method, f"{self._base()}{path}",
                json=payload, headers={"X-CSRF-Token": csrf},
            )
            if resp.status_code in (401, 403):
                _AUTH_CACHE.pop(self.node.id, None)
                cookies, csrf = await self._auth()
                async with self._client(cookies) as client2:
                    resp = await client2.request(
                        method, f"{self._base()}{path}",
                        json=payload, headers={"X-CSRF-Token": csrf},
                    )
            if resp.status_code >= 400:
                raise RuntimeError(f"3x-ui {method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"3x-ui {path}: {data.get('msg') or 'api error'}")
            return data

    def _inbound_id(self) -> int:
        return int(self.node.extra["inbound_id"])

    async def _get_clients(self) -> list[dict]:
        data = await self._request("GET", f"/panel/api/inbounds/get/{self._inbound_id()}")
        obj = data.get("obj") or {}
        settings = obj.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings or "{}")
        return (settings or {}).get("clients", []) or []

    @staticmethod
    def _match(client: dict, account) -> bool:
        return client.get("email") == account.username or client.get("id") == account.uuid

    def _client_obj(self, uuid: str, email: str, sub_id: str, enable: bool,
                    expiry: int = 0) -> dict:
        return {
            "id": uuid,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": expiry,
            "enable": enable,
            "tgId": "",
            "subId": sub_id,
            "reset": 0,
        }

    async def create_account(self, db, service, product) -> dict:
        uuid = security.new_uuid()
        email = f"u{service.user_id}_{uuid[:8]}@itkam34.ru"
        sub_id = security.new_sub_id()
        obj = self._client_obj(uuid, email, sub_id, True)
        payload = {
            "id": self._inbound_id(),
            "settings": json.dumps({"clients": [obj]}, ensure_ascii=False),
        }
        await self._request("POST", "/panel/api/inbounds/addClient", payload)
        return {
            "uuid": uuid,
            "username": email,
            "external_id": email,
            "secret_enc": security.encrypt_secret(uuid),
            "extra": {"sub_id": sub_id, "inbound_id": self._inbound_id()},
        }

    async def _update_client(self, account, mutator) -> None:
        clients = await self._get_clients()
        target = next((c for c in clients if self._match(c, account)), None)
        if target is None:
            raise RuntimeError(f"client {account.username} not found in inbound {self._inbound_id()}")
        target = mutator(dict(target))
        payload = {
            "id": self._inbound_id(),
            "settings": json.dumps({"clients": [target]}, ensure_ascii=False),
        }
        await self._request("POST", f"/panel/api/inbounds/updateClient/{account.uuid}", payload)

    async def push_limits(self, account, expiry_ms: int, enable: bool) -> None:
        def mut(c):
            c["enable"] = enable
            c["expiryTime"] = expiry_ms
            return c
        await self._update_client(account, mut)

    async def suspend_account(self, db, account) -> None:
        await self.push_limits(account, 0, False)

    async def resume_account(self, db, account) -> None:
        await self.push_limits(account, 0, True)

    async def delete_account(self, db, account) -> None:
        await self._request(
            "POST",
            f"/panel/api/inbounds/{self._inbound_id()}/delClient/{account.uuid}",
            {},
        )

    async def fetch_client_state(self, account) -> dict:
        for c in await self._get_clients():
            if self._match(c, account):
                return {
                    "enable": c.get("enable"),
                    "expiryTime": c.get("expiryTime"),
                    "up": c.get("up"),
                    "down": c.get("down"),
                }
        return {}

    def render_config(self, db, account) -> dict:
        extra = self.node.extra
        link = (
            f"vless://{account.uuid}@{self.node.endpoint_host}:{self.node.endpoint_port}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={extra.get('sni', '')}&fp={extra.get('fp', 'chrome')}"
            f"&pbk={extra.get('pbk', '')}&sid={extra.get('sid', '')}&spx=%2F"
            f"&type=tcp&headerType=none#{account.username}"
        )
        sub_base = extra.get("subscription_base")
        sub_url = f"{sub_base}/sub/{account.extra.get('sub_id', '')}" if sub_base else None
        return {"link": link, "subscription_url": sub_url, "config_text": None}
