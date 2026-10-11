from app.adapters.vpn.base import VpnAdapter


class OpenVpnStubAdapter(VpnAdapter):
    async def create_account(self, db, service, product) -> dict:
        raise NotImplementedError("OpenVPN adapter will be implemented in sprint 2")

    async def suspend_account(self, db, account) -> None:
        raise NotImplementedError

    async def resume_account(self, db, account) -> None:
        raise NotImplementedError

    async def delete_account(self, db, account) -> None:
        raise NotImplementedError
