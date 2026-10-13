import base64
import logging
import shlex

import asyncssh
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from app.adapters.vpn.base import VpnAdapter
from app.core import security
from app.services import ipam

log = logging.getLogger(__name__)


class WireGuardSshAdapter(VpnAdapter):
    async def _ssh_exec(self, cmd: str) -> str:
        key_data = security.decrypt_secret(self.node.ssh_key_enc)
        # Ключ импортируем из памяти — без временных файлов на диске.
        key = asyncssh.import_private_key(key_data)
        # Проверка ключа хоста: в node.extra["ssh_known_hosts"] кладём строку(и) known_hosts.
        # Без неё соединение уязвимо к MITM (под root-командами sudo!).
        known = self.node.extra.get("ssh_known_hosts")
        if known:
            known_hosts = asyncssh.import_known_hosts(known)
        else:
            log.warning("node %s: ssh_known_hosts not set, host key is NOT verified", self.node.code)
            known_hosts = None
        async with asyncssh.connect(
            self.node.ssh_host,
            port=self.node.ssh_port,
            username=self.node.ssh_user,
            client_keys=[key],
            known_hosts=known_hosts,
            connect_timeout=15,
        ) as conn:
            result = await conn.run(cmd, check=True, timeout=60)
            return result.stdout or ""

    def _gen_keypair(self) -> tuple[str, str]:
        priv = X25519PrivateKey.generate()
        priv_b64 = base64.b64encode(
            priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        ).decode()
        pub_b64 = base64.b64encode(
            priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode()
        return priv_b64, pub_b64

    async def create_account(self, db, service, product) -> dict:
        priv_b64, pub_b64 = self._gen_keypair()
        ip = ipam.allocate_ip(db, self.node)
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer add {shlex.quote(pub_b64)} {shlex.quote(ip)}")
        return {
            "username": f"wg-{service.id}",
            "public_key": pub_b64,
            "ip_address": ip,
            "secret_enc": security.encrypt_secret(priv_b64),
            "extra": {"protocol": "wireguard"},
        }

    async def suspend_account(self, db, account) -> None:
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer remove {shlex.quote(account.public_key)}")

    async def resume_account(self, db, account) -> None:
        await self._ssh_exec(
            f"sudo /usr/local/sbin/wg-peer add {shlex.quote(account.public_key)} "
            f"{shlex.quote(str(account.ip_address).split('/')[0])}"
        )

    async def delete_account(self, db, account) -> None:
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer remove {shlex.quote(account.public_key)}")

    def render_config(self, db, account) -> dict:
        priv_b64 = security.decrypt_secret(account.secret_enc)
        conf = (
            "[Interface]\n"
            f"PrivateKey = {priv_b64}\n"
            f"Address = {str(account.ip_address).split('/')[0]}/32\n"
            "DNS = 1.1.1.1\n\n"
            "[Peer]\n"
            f"PublicKey = {self.node.public_key}\n"
            f"Endpoint = {self.node.endpoint_host}:{self.node.endpoint_port}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
        )
        return {"link": None, "subscription_url": None, "config_text": conf}
