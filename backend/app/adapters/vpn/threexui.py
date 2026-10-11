import asyncio
import hashlib
import json
import re

import httpx

from app.adapters.vpn.base import VpnAdapter
from app.core import security

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 billing-core/1.0"}
CSRF_RE = re.compile(
    r'name="csrf-token"\s+content="([^"]+)"|content="([^"]+)"\s+name="csrf-token"'
)
INBOUND_KEYS = (
    "up", "down", "total", "remark", "enable", "expiryTime",
    "listen", "port", "protocol", "streamSettings", "sniffing", "allocate",
)

_SESSIONS: dict[int, dict] = {}
_LOCKS: dict[int, asyncio.Lock] = {}


class ThreeXuiAdapter(VpnAdapter):
    def _base(self) -> str:
        return self.node.api_url.rstrip("/")

    def _password(self) -> str:
        return security.decrypt_secret(self.node.api_key_enc)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            verify=self.node.extra.get("verify_tls", False),
            headers=UA,
            follow_redirects=True,
        )

    async def _login(self, client: httpx.AsyncClient) -> str:
        page = await client.get(f"{self._base()}/panel/")
        csrf = ""
        m = CSRF_RE.search(page.text or "")
        if m:
            csrf = m.group(1) or m.group(2) or ""
        user, pwd = self.node.api_user, self._password()
        headers = {"Referer": f"{self._base()}/panel/", "X-CSRF-Token": csrf}
        resp = await client.post(
            f"{self._base()}/login",
            json={"username": user, "password": pwd},
            headers=headers,
        )
        if resp.status_code >= 400:
            headers["X-XSRF-Token"] = csrf
            resp = await client.post(
                f"{self._base()}/login",
                data={"username": user, "password": pwd},
                headers=headers,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"3x-ui login failed: HTTP {resp.status_code} {resp.text[:200]}")
        return csrf

    async def _session(self) -> tuple[httpx.AsyncClient, str]:
        node_id = self.node.id
        lock = _LOCKS.setdefault(node_id, asyncio.Lock())
        async with lock:
            sess = _SESSIONS.get(node_id)
            if sess is None:
                client = self._client()
                csrf = await self._login(client)
                sess = {"client": client, "csrf": csrf}
                _SESSIONS[node_id] = sess
            return sess["client"], sess["csrf"]

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        client, csrf = await self._session()
        resp = await client.request(
            method, f"{self._base()}{path}",
            json=payload, headers={"X-CSRF-Token": csrf},
        )
        if resp.status_code in (401, 403):
            csrf = await self._login(client)
            _SESSIONS[self.node.id]["csrf"] = csrf
            resp = await client.request(
                method, f"{self._base()}{path}",
                json=payload, headers={"X-CSRF-Token": csrf},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"3x-ui {method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()

    def _inbound_id(self) -> int:
        return int(self.node.extra["inbound_id"])

    async def _get_inbound(self) -> dict:
        data = await self._request("GET", f"/panel/api/inbounds/get/{self._inbound_id()}")
        obj = data.get("obj")
        if obj is None:
            data = await self._request("GET", "/panel/api/inbounds/list")
            for item in data.get("obj") or []:
                if item.get("id") == self._inbound_id():
                    obj = item
                    break
        if obj is None:
            raise RuntimeError(f"inbound {self._inbound_id()} not found in panel")
        return obj

    @staticmethod
    def _parse_settings(inbound: dict) -> dict:
        settings = inbound.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings or "{}")
        return settings or {}

    async def _mutate_clients(self, mutator) -> None:
        inbound = await self._get_inbound()
        settings = self._parse_settings(inbound)
        settings["clients"] = mutator(settings.get("clients", []))
        payload = {k: inbound.get(k) for k in INBOUND_KEYS if k in inbound}
        payload["settings"] = json.dumps(settings, ensure_ascii=False)
        await self._request("POST", f"/panel/api/inbounds/update/{self._inbound_id()}", payload)

    def _client_obj(self, account_uuid: str, email: str, sub_id: str, enable: bool) -> dict:
        return {
            "id": account_uuid,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": enable,
            "tgId": "",
            "subId": sub_id,
            "reset": 0,
        }

    @staticmethod
    def _match(client: dict, account) -> bool:
        return client.get("email") == account.username or client.get("id") == account.uuid

    async def create_account(self, db, service, product) -> dict:
        account_uuid = security.new_uuid()
        email = f"u{service.user_id}_{hashlib.sha256(str(service.id).encode()).hexdigest()[:8]}@itkam34.ru"
        sub_id = security.new_sub_id()
        obj = self._client_obj(account_uuid, email, sub_id, True)

        def add(clients):
            clients = [c for c in clients if c.get("email") != email]
            return clients + [obj]

        await self._mutate_clients(add)
        return {
            "uuid": account_uuid,
            "username": email,
            "external_id": email,
            "secret_enc": security.encrypt_secret(account_uuid),
            "extra": {"sub_id": sub_id, "inbound_id": self._inbound_id()},
        }

    async def push_limits(self, account, expiry_ms: int, enable: bool) -> None:
        def mut(clients):
            for c in clients:
                if self._match(c, account):
                    c["enable"] = enable
                    c["expiryTime"] = expiry_ms
            return clients
        await self._mutate_clients(mut)

    async def fetch_client_state(self, account) -> dict:
        inbound = await self._get_inbound()
        for c in self._parse_settings(inbound).get("clients", []):
            if self._match(c, account):
                return {
                    "enable": c.get("enable"),
                    "expiryTime": c.get("expiryTime"),
                    "up": c.get("up"),
                    "down": c.get("down"),
                }
        return {}

    async def suspend_account(self, db, account) -> None:
        await self.push_limits(account, 0, False)

    async def resume_account(self, db, account) -> None:
        def mut(clients):
            for c in clients:
                if self._match(c, account):
                    c["enable"] = True
            return clients
        await self._mutate_clients(mut)

    async def delete_account(self, db, account) -> None:
        def mut(clients):
            return [c for c in clients if not self._match(c, account)]
        await self._mutate_clients(mut)

    def render_config(self, db, account) -> dict:
        extra = self.node.extra
        link = (
            f"vless://{account.uuid}@{self.node.endpoint_host}:{self.node.endpoint_port}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={extra.get('sni', '')}&fp={extra.get('fp', 'firefox')}"
            f"&pbk={extra.get('pbk', '')}&sid={extra.get('sid', '')}&spx=%2F"
            f"&type=tcp&headerType=none#{account.username}"
        )
        sub_base = extra.get("subscription_base")
        sub_url = f"{sub_base}/sub/{account.extra.get('sub_id', '')}" if sub_base else None
        return {"link": link, "subscription_url": sub_url, "config_text": None}
