import asyncio

from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.core import security
from app.db import SessionLocal, engine
from app.models import (
    LedgerEntry, PaymentRequest, Product, ProvisioningTask, ServiceInstance,
    UsageSession, User, VpnAccount, VpnNode, Wallet,
)
from app.services import ledger


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = (form.get("username") or "").strip().lower()
        password = form.get("password") or ""
        db = SessionLocal()
        try:
            user = db.execute(
                select(User).where(
                    User.email == email, User.role == "admin", User.status == "active"
                )
            ).scalar_one_or_none()
            if user is not None and security.verify_password(password, user.password_hash):
                request.session.update({"admin_uid": user.id})
                return True
        finally:
            db.close()
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin_uid"))


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.role, User.status, User.created_at]
    column_searchable = [User.email]
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa fa-users"


class WalletAdmin(ModelView, model=Wallet):
    column_list = [Wallet.id, Wallet.user_id, Wallet.balance_minor]
    name = "Кошелёк"
    name_plural = "Кошельки"
    icon = "fa fa-wallet"


class LedgerAdmin(ModelView, model=LedgerEntry):
    column_list = [LedgerEntry.id, LedgerEntry.wallet_id, LedgerEntry.entry_type,
                   LedgerEntry.amount_minor, LedgerEntry.reason, LedgerEntry.created_at]
    can_create = False
    can_edit = False
    can_delete = False
    name = "Операция"
    name_plural = "Финансовый журнал (ledger)"
    icon = "fa fa-receipt"


class ProductAdmin(ModelView, model=Product):
    column_list = [Product.id, Product.code, Product.name, Product.service_type,
                   Product.unit, Product.price_minor, Product.active]
    name = "Продукт"
    name_plural = "Продукты и тарифы"
    icon = "fa fa-box"


class ServiceAdmin(ModelView, model=ServiceInstance):
    column_list = [ServiceInstance.id, ServiceInstance.user_id, ServiceInstance.product_id,
                   ServiceInstance.name, ServiceInstance.status, ServiceInstance.created_at]
    name = "Услуга клиента"
    name_plural = "Услуги клиентов (реазируемые)"
    icon = "fa fa-cube"


class NodeAdmin(ModelView, model=VpnNode):
    column_list = [VpnNode.id, VpnNode.code, VpnNode.name, VpnNode.country,
                   VpnNode.protocol, VpnNode.api_kind, VpnNode.active]
    name = "VPN-нода"
    name_plural = "VPN-ноды"
    icon = "fa fa-server"


class AccountAdmin(ModelView, model=VpnAccount):
    column_list = [VpnAccount.id, VpnAccount.service_instance_id, VpnAccount.node_id,
                   VpnAccount.username, VpnAccount.status]
    name = "VPN-аккаунт"
    name_plural = "VPN-аккаунты"
    icon = "fa fa-user-shield"


class UsageAdmin(ModelView, model=UsageSession):
    column_list = [UsageSession.id, UsageSession.service_instance_id,
                   UsageSession.vpn_account_id, UsageSession.status,
                   UsageSession.started_at, UsageSession.last_heartbeat_at, UsageSession.cost_minor]
    can_create = False
    can_edit = False
    can_delete = False
    name = "Сессия использования"
    name_plural = "Сессии использования"
    icon = "fa fa-clock"


class TaskAdmin(ModelView, model=ProvisioningTask):
    column_list = [ProvisioningTask.id, ProvisioningTask.entity_type,
                   ProvisioningTask.entity_id, ProvisioningTask.action,
                   ProvisioningTask.status, ProvisioningTask.attempts]
    can_create = False
    can_edit = False
    name = "Задача выдачи"
    name_plural = "Задачи выдачи (provisioning)"
    icon = "fa fa-list-check"


class PaymentAdmin(ModelView, model=PaymentRequest):
    column_list = [PaymentRequest.id, PaymentRequest.user_id, PaymentRequest.amount_minor,
                   PaymentRequest.method, PaymentRequest.status, PaymentRequest.created_at]
    can_create = False
    can_edit = False
    can_delete = True
    name = "Заявка на пополнение"
    name_plural = "Заявки на пополнение"
    icon = "fa fa-money-bill"

    def _redirect_list(self, request: Request):
        return RedirectResponse(f"{request.base_url}admin/payment-request/list", status_code=302)

    @action(name="approve", label="Одобрить и зачислить",
            confirmation_message="Зачислить сумму на кошелёк клиента?")
    async def approve(self, request: Request, pk):
        def _sync():
            db = SessionLocal()
            try:
                pr = db.get(PaymentRequest, int(pk))
                if pr is not None and pr.status == "pending":
                    wallet = ledger.get_wallet(db, pr.user_id)
                    ledger.credit(
                        db, wallet, pr.amount_minor,
                        reason=f"payment_{pr.method}",
                        entity_type="payment_request", entity_id=pr.id,
                        idempotency_key=f"payreq:{pr.id}",
                    )
                    pr.status = "approved"
                    db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_sync)
        return self._redirect_list(request)

    @action(name="reject", label="Отклонить",
            confirmation_message="Отклонить заявку без зачисления?")
    async def reject(self, request: Request, pk):
        def _sync():
            db = SessionLocal()
            try:
                pr = db.get(PaymentRequest, int(pk))
                if pr is not None and pr.status == "pending":
                    pr.status = "rejected"
                    db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_sync)
        return self._redirect_list(request)


def setup_admin(app):
    admin = Admin(
        app, engine,
        authentication_backend=AdminAuth(),
        title="ITKAM34 Billing",
        base_url="/admin",
    )
    for view in (UserAdmin, WalletAdmin, LedgerAdmin, ProductAdmin, ServiceAdmin,
                 NodeAdmin, AccountAdmin, UsageAdmin, TaskAdmin, PaymentAdmin):
        admin.add_view(view)
    return admin
