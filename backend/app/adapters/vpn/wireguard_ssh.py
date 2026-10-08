import base64
import os
import tempfile

import asyncssh
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from app.adapters.vpn.base import VpnAdapter
from app.core import security
from app.services import ipam


class WireGuardSshAdapter(VpnAdapter):
    """Управляет пирами wg0 через SSH-скрипт /usr/local/sbin/wg-peer."""

    async def _ssh_exec(self, cmd: str) -> str:
        key_data = security.decrypt_secret(self.node.ssh_key_enc)
        fd, path = tempfile.mkstemp(suffix=".key")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(key_data)
            os.chmod(path, 0o600)
            async with asyncssh.connect(
                self.node.ssh_host,
                port=self.node.ssh_port,
                username=self.node.ssh_user,
                client_keys=[path],
                known_hosts=None,
            ) as conn:
                result = await conn.run(cmd, check=True)
                return result.stdout or ""
        finally:
            os.unlink(path)

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
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer add {pub_b64} {ip}")
        return {
            "username": f"wg-{service.id}",
            "public_key": pub_b64,
            "ip_address": ip,
            "secret_enc": security.encrypt_secret(priv_b64),
            "extra": {"protocol": "wireguard"},
        }

    async def suspend_account(self, db, account) -> None:
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer remove {account.public_key}")

    async def resume_account(self, db, account) -> None:
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer add {account.public_key} {account.ip_address}")

    async def delete_account(self, db, account) -> None:
        await self._ssh_exec(f"sudo /usr/local/sbin/wg-peer remove {account.public_key}")

    def render_config(self, db, account) -> dict:
        priv_b64 = security.decrypt_secret(account.secret_enc)
        conf = (
            "[Interface]\n"
            f"PrivateKey = {priv_b64}\n"
            f"Address = {account.ip_address}/32\n"
            "DNS = 1.1.1.1\n\n"
            "[Peer]\n"
            f"PublicKey = {self.node.public_key}\n"
            f"Endpoint = {self.node.endpoint_host}:{self.node.endpoint_port}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
        )
        return {"link": None, "subscription_url": None, "config_text": conf}