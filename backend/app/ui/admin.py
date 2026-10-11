from sqlalchemy import select
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core import security
from app.db import SessionLocal, engine
from app.models import (
    LedgerEntry, Product, ProvisioningTask, ServiceInstance, UsageSession,
    User, VpnAccount, VpnNode, Wallet,
)


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = (form.get("username") or "").strip()
        password = form.get("password") or ""
        db = SessionLocal()
        try:
            user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user and user.role == "admin" and user.status == "active" \
                    and security.verify_password(password, user.password_hash):
                request.session.update({"admin_uid": user.id})
                return True
            return False
        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("admin_uid") is not None


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.role, User.status, User.created_at]
    column_searchable_list = [User.email]
    name = "Пользователь"
    name_plural = "Пользователи"


class WalletAdmin(ModelView, model=Wallet):
    column_list = [Wallet.id, Wallet.user_id, Wallet.currency, Wallet.balance_minor]
    can_create = False
    can_delete = False
    name = "Кошелёк"
    name_plural = "Кошельки"


class LedgerAdmin(ModelView, model=LedgerEntry):
    column_list = [LedgerEntry.id, LedgerEntry.wallet_id, LedgerEntry.amount_minor,
                   LedgerEntry.balance_after_minor, LedgerEntry.entry_type,
                   LedgerEntry.reason, LedgerEntry.idempotency_key, LedgerEntry.created_at]
    can_create = False
    can_edit = False
    can_delete = False
    name = "Операция ledger"
    name_plural = "Ledger (финансовый журнал)"


class ProductAdmin(ModelView, model=Product):
    column_list = [Product.id, Product.code, Product.service_type, Product.unit,
                   Product.price_minor, Product.active]
    name = "Продукт"
    name_plural = "Продукты"


class ServiceAdmin(ModelView, model=ServiceInstance):
    column_list = [ServiceInstance.id, ServiceInstance.user_id, ServiceInstance.product_id,
                   ServiceInstance.name, ServiceInstance.status, ServiceInstance.created_at]
    name = "Услуга"
    name_plural = "Услуги"


class NodeAdmin(ModelView, model=VpnNode):
    column_list = [VpnNode.id, VpnNode.code, VpnNode.country, VpnNode.protocol,
                   VpnNode.api_kind, VpnNode.active]
    column_details_exclude_list = [VpnNode.api_key_enc, VpnNode.ssh_key_enc]
    name = "VPN-нода"
    name_plural = "VPN-ноды"


class AccountAdmin(ModelView, model=VpnAccount):
    column_list = [VpnAccount.id, VpnAccount.service_instance_id, VpnAccount.node_id,
                   VpnAccount.protocol, VpnAccount.username, VpnAccount.status]
    column_details_exclude_list = [VpnAccount.secret_enc]
    name = "VPN-аккаунт"
    name_plural = "VPN-аккаунты"


class UsageAdmin(ModelView, model=UsageSession):
    column_list = [UsageSession.id, UsageSession.vpn_account_id, UsageSession.started_at,
                   UsageSession.ended_at, UsageSession.charged_minutes,
                   UsageSession.cost_minor, UsageSession.status]
    can_create = False
    can_edit = False
    can_delete = False
    name = "Сессия использования"
    name_plural = "Сессии использования"


class TaskAdmin(ModelView, model=ProvisioningTask):
    column_list = [ProvisioningTask.id, ProvisioningTask.entity_type, ProvisioningTask.entity_id,
                   ProvisioningTask.action, ProvisioningTask.status,
                   ProvisioningTask.attempts, ProvisioningTask.error]
    can_create = False
    can_delete = False
    name = "Задача provisioning"
    name_plural = "Задачи provisioning"


def setup_admin(app, secret_key: str) -> None:
    auth = AdminAuth(secret_key=secret_key)
    admin = Admin(
        app, engine,
        authentication_backend=auth,
        title="ITKAM34 Billing",
        base_url="/admin",
    )
    for view in (UserAdmin, WalletAdmin, LedgerAdmin, ProductAdmin, ServiceAdmin,
                 NodeAdmin, AccountAdmin, UsageAdmin, TaskAdmin):
        admin.add_view(view)
