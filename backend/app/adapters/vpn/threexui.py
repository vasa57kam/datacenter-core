import hashlib
import json
import re
import threading
from urllib.parse import quote

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

# Кэшируем только cookie+CSRF (а не httpx-клиент): воркер вызывает asyncio.run() на каждую
# операцию, и клиент/Lock, привязанные к закрытому event loop, ломаются ("Event loop is closed").
_AUTH: dict[int, dict] = {}
# Панель правится по схеме «прочитал inbound целиком → записал целиком», поэтому
# параллельные изменения из разных потоков воркера затирали бы друг друга.
_PANEL_LOCK = threading.Lock()


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

    def _save_auth(self, client: httpx.AsyncClient, csrf: str) -> None:
        _AUTH[self.node.id] = {"cookies": dict(client.cookies.items()), "csrf": csrf}

    async def _send(self, client, method, path, payload, csrf):
        resp = await client.request(
            method, f"{self._base()}{path}",
            json=payload, headers={"X-CSRF-Token": csrf},
        )
        data = None
        if resp.status_code < 400:
            try:
                data = resp.json()
            except ValueError:
                data = None  # HTML вместо JSON — обычно страница логина (сессия протухла)
        return resp, data

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        async with self._client() as client:
            auth = _AUTH.get(self.node.id)
            cached = auth is not None
            if cached:
                client.cookies.update(auth["cookies"])
                csrf = auth["csrf"]
            else:
                csrf = await self._login(client)
                self._save_auth(client, csrf)

            resp, data = await self._send(client, method, path, payload, csrf)
            # 3x-ui на неавторизованный запрос может ответить 401/403/404 или страницей логина
            if cached and (resp.status_code in (401, 403, 404) or (resp.status_code < 400 and data is None)):
                csrf = await self._login(client)
                self._save_auth(client, csrf)
                resp, data = await self._send(client, method, path, payload, csrf)

            if resp.status_code >= 400:
                raise RuntimeError(f"3x-ui {method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
            if data is None:
                raise RuntimeError(f"3x-ui {method} {path}: non-JSON response")
            # Панель отвечает HTTP 200 даже при ошибке — признак в поле success.
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"3x-ui {method} {path}: {data.get('msg', 'unknown error')}")
            return data

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
        with _PANEL_LOCK:
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
            f"&type=tcp&headerType=none#{quote(account.username or '', safe='')}"
        )
        sub_base = extra.get("subscription_base")
        sub_url = f"{sub_base}/sub/{account.extra.get('sub_id', '')}" if sub_base else None
        return {"link": link, "subscription_url": sub_url, "config_text": None}
