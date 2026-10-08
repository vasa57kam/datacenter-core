class VpnAdapter:
    def __init__(self, node):
        self.node = node

    async def create_account(self, db, service, product) -> dict:
        raise NotImplementedError

    async def suspend_account(self, db, account) -> None:
        raise NotImplementedError

    async def resume_account(self, db, account) -> None:
        raise NotImplementedError

    async def delete_account(self, db, account) -> None:
        raise NotImplementedError

    def render_config(self, db, account) -> dict:
        return {}