import json

import httpx

from app.adapters.vpn.base import VpnAdapter
from app.core import security


class ThreeXuiAdapter(VpnAdapter):
    """Адаптер панели 3x-ui (VLESS Reality)."""

    def _base(self) -> str:
        return self.node.api_url.rstrip("/")

    def _password(self) -> str:
        return security.decrypt_secret(self.node.api_key_enc)

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            verify=self.node.extra.get("verify_tls", False),
        )

    async def _login(self, client: httpx.AsyncClient) -> None:
        payload = {"username": self.node.api_user, "password": self._password()}
        resp = await client.post(f"{self._base()}/login", json=payload)
        if resp.status_code in (400, 404):
            resp = await client.post(f"{self._base()}/login", data=payload)
        resp.raise_for_status()

    async def _post(self, path: str, payload: dict | None = None) -> dict:
        async with await self._client() as client:
            await self._login(client)
            resp = await client.post(f"{self._base()}{path}", json=payload or {})
            resp.raise_for_status()
            return resp.json()

    async def _get(self, path: str) -> dict:
        async with await self._client() as client:
            await self._login(client)
            resp = await client.get(f"{self._base()}{path}")
            resp.raise_for_status()
            return resp.json()

    def _inbound_id(self) -> int:
        return int(self.node.extra["inbound_id"])

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

    async def create_account(self, db, service, product) -> dict:
        account_uuid = security.new_uuid()
        email = f"svc{service.id}@itkam34.ru"
        sub_id = security.new_sub_id()
        client_obj = self._client_obj(account_uuid, email, sub_id, True)

        await self._post(
            "/panel/api/inbounds/addClient",
            {"id": self._inbound_id(), "settings": json.dumps({"clients": [client_obj]})},
        )
        return {
            "uuid": account_uuid,
            "username": email,
            "external_id": email,
            "secret_enc": security.encrypt_secret(account_uuid),
            "extra": {"sub_id": sub_id, "inbound_id": self._inbound_id()},
        }

    async def _update_client(self, account, enable: bool) -> None:
        sub_id = account.extra.get("sub_id", "")
        client_obj = self._client_obj(account.uuid, account.username, sub_id, enable)
        await self._post(
            f"/panel/api/inbounds/updateClient/{account.uuid}",
            {"id": self._inbound_id(), "settings": json.dumps({"clients": [client_obj]})},
        )

    async def suspend_account(self, db, account) -> None:
        await self._update_client(account, False)

    async def resume_account(self, db, account) -> None:
        await self._update_client(account, True)

    async def delete_account(self, db, account) -> None:
        await self._post(f"/panel/api/inbounds/{self._inbound_id()}/delClient/{account.uuid}")

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