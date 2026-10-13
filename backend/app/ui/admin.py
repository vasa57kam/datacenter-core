import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core import security
from app.db import SessionLocal, engine
from app.models import (
    LedgerEntry, PaymentRequest, Product, ProvisioningTask, ServiceInstance,
    UsageSession, User, VpnAccount, VpnNode, Wallet,
)


def rub(value) -> str:
    return f"{(value or 0) / 100:.2f} ₽"


def mb(value) -> str:
    return f"{(value or 0) / 1048576:.1f} МБ"


STATUS_CHOICES = [
    ("pending", "ожидает"),
    ("provisioning", "выдаётся"),
    ("active", "активна"),
    ("suspended", "приостановлена"),
    ("terminated", "завершена"),
]


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = security.normalize_email(form.get("username") or "")
        password = form.get("password") or ""
        db = SessionLocal()
        try:
            user = db.execute(
                select(User).where(func.lower(User.email) == email)
            ).scalar_one_or_none()
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
        uid = request.session.get("admin_uid")
        if uid is None:
            return False

        def check() -> bool:
            db = SessionLocal()
            try:
                user = db.get(User, int(uid))
                return bool(user and user.role == "admin" and user.status == "active")
            finally:
                db.close()

        # Права перепроверяем в БД: разжалованный/заблокированный админ теряет доступ сразу.
        return await asyncio.to_thread(check)


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.role, User.status, User.created_at]
    column_searchable_list = [User.email]
    column_labels = {
        User.id: "№", User.email: "Email (логин)", User.role: "Роль",
        User.status: "Состояние", User.created_at: "Регистрация",
    }
    form_choices = {
        User.role: [("client", "клиент"), ("admin", "админ"), ("manager", "менеджер"), ("master", "мастер")],
        User.status: [("active", "активен"), ("blocked", "заблокирован")],
    }
    column_formatters = {User.created_at: lambda m, a: m.created_at.strftime("%d.%m.%Y %H:%M")}
    form_excluded_columns = [User.password_hash]
    column_details_exclude_list = [User.password_hash]
    can_delete = False
    name = "Пользователь"
    name_plural = "Пользователи"


class WalletAdmin(ModelView, model=Wallet):
    column_list = [Wallet.id, Wallet.user_id, Wallet.currency, Wallet.balance_minor]
    column_labels = {
        Wallet.id: "№", Wallet.user_id: "Клиент", Wallet.currency: "Валюта",
        Wallet.balance_minor: "Баланс",
    }
    column_formatters = {
        Wallet.balance_minor: lambda m, a: rub(m.balance_minor),
        Wallet.user_id: lambda m, a: m.user.email if m.user else m.user_id,
    }
    can_create = False
    can_edit = False  # баланс меняется только проводками ledger, не руками
    can_delete = False
    name = "Кошелёк"
    name_plural = "Кошельки"

    def list_query(self, request: Request):
        return select(Wallet).options(selectinload(Wallet.user))


class LedgerAdmin(ModelView, model=LedgerEntry):
    column_list = [LedgerEntry.id, LedgerEntry.wallet_id, LedgerEntry.entry_type,
                   LedgerEntry.amount_minor, LedgerEntry.balance_after_minor,
                   LedgerEntry.reason, LedgerEntry.created_at]
    column_labels = {
        LedgerEntry.id: "№", LedgerEntry.wallet_id: "Клиент",
        LedgerEntry.entry_type: "Операция", LedgerEntry.amount_minor: "Сумма",
        LedgerEntry.balance_after_minor: "Баланс после", LedgerEntry.reason: "Назначение",
        LedgerEntry.created_at: "Когда",
    }
    column_formatters = {
        LedgerEntry.amount_minor: lambda m, a: ("+ " if m.entry_type == "credit" else "− ") + rub(abs(m.amount_minor)),
        LedgerEntry.balance_after_minor: lambda m, a: rub(m.balance_after_minor),
        LedgerEntry.entry_type: lambda m, a: "приход" if m.entry_type == "credit" else "списание",
        LedgerEntry.created_at: lambda m, a: m.created_at.strftime("%d.%m.%Y %H:%M:%S"),
        LedgerEntry.wallet_id: lambda m, a: m.wallet.user.email if m.wallet and m.wallet.user else m.wallet_id,
    }
    can_create = False
    can_edit = False
    can_delete = False
    name = "Операция"
    name_plural = "Финансовый журнал (ledger)"

    def list_query(self, request: Request):
        return select(LedgerEntry).options(
            selectinload(LedgerEntry.wallet).selectinload(Wallet.user)
        )


class ProductAdmin(ModelView, model=Product):
    column_list = [Product.id, Product.name, Product.code, Product.service_type,
                   Product.unit, Product.price_minor, Product.active]
    column_labels = {
        Product.id: "№", Product.name: "Название для клиента", Product.code: "Код (служебный)",
        Product.service_type: "Тип услуги", Product.unit: "Тарификация",
        Product.price_minor: "Цена", Product.active: "В продаже",
        Product.config: "Доп. параметры (JSON)", Product.currency: "Валюта",
    }
    column_formatters = {
        Product.price_minor: lambda m, a: rub(m.price_minor) + " / " + {"second": "сек", "minute": "мин", "hour": "ч", "day": "день", "month": "мес"}.get(m.unit, "раз"),
    }
    form_choices = {
        Product.service_type: [("vpn", "VPN"), ("vps", "VPS/серверы"), ("cctv", "Видеонаблюдение"),
                               ("hosting", "Хостинг"), ("storage", "Хранилище"), ("mail", "Почта")],
        Product.unit: [("second", "посекундно"), ("minute", "поминутно"), ("hour", "почасово"), ("day", "в день"), ("month", "помесячно"), ("one_time", "разовый платёж")],
    }
    can_delete = False
    name = "Продукт"
    name_plural = "Продукты и тарифы"


class ServiceAdmin(ModelView, model=ServiceInstance):
    column_list = [ServiceInstance.id, ServiceInstance.user_id, ServiceInstance.name,
                   ServiceInstance.status, ServiceInstance.created_at]
    column_labels = {
        ServiceInstance.id: "№", ServiceInstance.user_id: "Клиент",
        ServiceInstance.product_id: "Продукт №", ServiceInstance.name: "Название услуги",
        ServiceInstance.status: "Статус", ServiceInstance.config: "Конфиг (JSON)",
        ServiceInstance.created_at: "Создана", ServiceInstance.updated_at: "Изменена",
    }
    form_choices = {ServiceInstance.status: STATUS_CHOICES}
    column_formatters = {
        ServiceInstance.created_at: lambda m, a: m.created_at.strftime("%d.%m.%Y %H:%M"),
        ServiceInstance.user_id: lambda m, a: m.user.email if m.user else m.user_id,
        ServiceInstance.status: lambda m, a: {
            "pending": "ожидает", "provisioning": "выдаётся", "active": "активна",
            "suspended": "приостановлена", "terminated": "завершена",
        }.get(m.status, m.status),
    }
    name = "Услуга"
    name_plural = "Услуги клиентов (редактируемые)"

    def list_query(self, request: Request):
        return select(ServiceInstance).options(selectinload(ServiceInstance.user))


class NodeAdmin(ModelView, model=VpnNode):
    column_list = [VpnNode.id, VpnNode.code, VpnNode.name, VpnNode.country,
                   VpnNode.protocol, VpnNode.api_kind, VpnNode.active]
    column_labels = {
        VpnNode.id: "№", VpnNode.code: "Код ноды", VpnNode.name: "Название",
        VpnNode.country: "Страна", VpnNode.protocol: "Протокол",
        VpnNode.api_kind: "Тип управления", VpnNode.active: "Активна",
        VpnNode.api_url: "URL панели", VpnNode.api_user: "Логин панели",
        VpnNode.endpoint_host: "Хост для клиентов", VpnNode.endpoint_port: "Порт для клиентов",
        VpnNode.subnet_cidr: "Подсеть WireGuard", VpnNode.public_key: "Публичный ключ сервера",
        VpnNode.extra: "Доп. параметры (inbound_id, sni, pbk, sid…)",
    }
    form_choices = {
        VpnNode.protocol: [("vless", "VLESS Reality"), ("wireguard", "WireGuard"), ("openvpn", "OpenVPN")],
        VpnNode.api_kind: [("3xui", "панель 3x-ui"), ("ssh_wireguard", "SSH + wg-peer"), ("openvpn_api", "OpenVPN API"), ("manual", "вручную")],
    }
    column_details_exclude_list = [VpnNode.api_key_enc, VpnNode.ssh_key_enc]
    can_delete = False

    async def on_model_change(self, data, model, is_created, request) -> None:
        # Секрет, введённый в форму открытым текстом, шифруем (Fernet-токены начинаются с "gAAAA").
        for field in ("api_key_enc", "ssh_key_enc"):
            value = data.get(field)
            if value and not str(value).startswith("gAAAA"):
                data[field] = security.encrypt_secret(str(value))

    name = "VPN-нода"
    name_plural = "VPN-ноды"


class AccountAdmin(ModelView, model=VpnAccount):
    column_list = [VpnAccount.id, VpnAccount.username, VpnAccount.protocol,
                   VpnAccount.status, VpnAccount.service_instance_id]
    column_labels = {
        VpnAccount.id: "№", VpnAccount.username: "Имя клиента в панели",
        VpnAccount.protocol: "Протокол", VpnAccount.status: "Статус",
        VpnAccount.service_instance_id: "Услуга №", VpnAccount.node_id: "Нода №",
        VpnAccount.ip_address: "IP (WireGuard)", VpnAccount.public_key: "Публичный ключ",
    }
    form_choices = {
        VpnAccount.status: [("pending", "ожидает"), ("active", "активен"),
                            ("suspended", "приостановлен"), ("deleted", "удалён")],
    }
    column_details_exclude_list = [VpnAccount.secret_enc]
    name = "VPN-аккаунт"
    name_plural = "VPN-аккаунты"


class UsageAdmin(ModelView, model=UsageSession):
    column_list = [UsageSession.id, UsageSession.vpn_account_id, UsageSession.started_at,
                   UsageSession.ended_at, UsageSession.charged_minutes, UsageSession.cost_minor,
                   UsageSession.status]
    column_labels = {
        UsageSession.id: "№", UsageSession.vpn_account_id: "Клиент в панели",
        UsageSession.started_at: "Начало", UsageSession.ended_at: "Конец",
        UsageSession.charged_minutes: "Списано минут", UsageSession.cost_minor: "Стоимость",
        UsageSession.rx_bytes: "Принято", UsageSession.tx_bytes: "Отдано",
        UsageSession.status: "Состояние",
    }
    column_formatters = {
        UsageSession.cost_minor: lambda m, a: rub(m.cost_minor),
        UsageSession.rx_bytes: lambda m, a: mb(m.rx_bytes),
        UsageSession.tx_bytes: lambda m, a: mb(m.tx_bytes),
        UsageSession.started_at: lambda m, a: m.started_at.strftime("%d.%m %H:%M"),
        UsageSession.ended_at: lambda m, a: m.ended_at.strftime("%d.%m %H:%M") if m.ended_at else "—",
        UsageSession.vpn_account_id: lambda m, a: m.account.username if m.account else m.vpn_account_id,
        UsageSession.status: lambda m, a: "идёт" if m.status == "active" else "закрыта",
    }
    can_create = False
    can_edit = False
    can_delete = False
    name = "Сессия"
    name_plural = "Сессии использования"

    def list_query(self, request: Request):
        return select(UsageSession).options(selectinload(UsageSession.account))


class TaskAdmin(ModelView, model=ProvisioningTask):
    column_list = [ProvisioningTask.id, ProvisioningTask.action, ProvisioningTask.status,
                   ProvisioningTask.attempts, ProvisioningTask.error, ProvisioningTask.updated_at]
    column_labels = {
        ProvisioningTask.id: "№", ProvisioningTask.action: "Действие",
        ProvisioningTask.status: "Статус", ProvisioningTask.attempts: "Попыток",
        ProvisioningTask.error: "Ошибка", ProvisioningTask.entity_id: "Услуга №",
        ProvisioningTask.updated_at: "Обновлена",
    }
    form_choices = {
        ProvisioningTask.action: [("create", "создать"), ("suspend", "приостановить"),
                                  ("resume", "возобновить"), ("delete", "удалить")],
        ProvisioningTask.status: [("pending", "в очереди"), ("running", "выполняется"),
                                  ("done", "готово"), ("error", "ошибка")],
    }
    can_create = False
    can_delete = False
    name = "Задача"
    name_plural = "Задачи выдачи (provisioning)"


class PaymentAdmin(ModelView, model=PaymentRequest):
    column_list = [PaymentRequest.id, PaymentRequest.user_id, PaymentRequest.amount_minor,
                   PaymentRequest.method, PaymentRequest.status, PaymentRequest.created_at]
    column_labels = {
        PaymentRequest.id: "№", PaymentRequest.user_id: "Клиент",
        PaymentRequest.amount_minor: "Сумма", PaymentRequest.method: "Способ",
        PaymentRequest.comment: "Комментарий", PaymentRequest.status: "Статус",
        PaymentRequest.created_at: "Создана", PaymentRequest.processed_at: "Обработана",
    }
    column_formatters = {
        PaymentRequest.amount_minor: lambda m, a: rub(m.amount_minor),
        PaymentRequest.user_id: lambda m, a: m.user.email if m.user else m.user_id,
        PaymentRequest.status: lambda m, a: {
            "pending": "на проверке", "approved": "зачислено", "rejected": "отклонено",
        }.get(m.status, m.status),
        PaymentRequest.created_at: lambda m, a: m.created_at.strftime("%d.%m.%Y %H:%M"),
    }
    form_choices = {
        PaymentRequest.method: [("transfer", "перевод на карту"), ("cash", "наличные"), ("other", "другое")],
    }
    can_create = False
    can_edit = False
    can_delete = False

    def list_query(self, request: Request):
        return select(PaymentRequest).options(selectinload(PaymentRequest.user))

    @action(name="approve", label="Одобрить и зачислить", confirmation_message="Зачислить платёж на баланс клиента?")
    async def approve(self, request: Request) -> None:
        await self._process(request, approve=True)

    @action(name="reject", label="Отклонить", confirmation_message="Отклонить заявку?")
    async def reject(self, request: Request) -> None:
        await self._process(request, approve=False)

    async def _process(self, request: Request, approve: bool) -> None:
        from app.services import ledger as _ledger
        pks = (request.query_params.get("pks") or "").split(",")
        
        def process_sync():
            db = SessionLocal()
            try:
                for pk in pks:
                    if not pk.strip():
                        continue
                    if not pk.strip().isdigit():
                        continue
                    # FOR UPDATE: двойной клик/два админа не зачислят заявку дважды
                    pr = db.execute(
                        select(PaymentRequest)
                        .where(PaymentRequest.id == int(pk))
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    ).scalar_one_or_none()
                    if pr is None or pr.status != "pending":
                        continue
                    if approve:
                        wallet = _ledger.get_wallet(db, pr.user_id)
                        _ledger.credit(
                            db, wallet, pr.amount_minor,
                            reason=f"payment_{pr.method}",
                            entity_type="payment_request",
                            entity_id=pr.id,
                            idempotency_key=f"payreq:{pr.id}:approve",
                        )
                        pr.status = "approved"
                    else:
                        pr.status = "rejected"
                    pr.processed_at = datetime.now(timezone.utc)
                    db.commit()  # по одной заявке: сбой на одной не откатывает уже зачисленные
            finally:
                db.close()
        
        await asyncio.to_thread(process_sync)

    name = "Заявка на пополнение"
    name_plural = "Заявки на пополнение"


def setup_admin(app, secret_key: str) -> None:
    auth = AdminAuth(secret_key=secret_key)
    admin = Admin(
        app, engine,
        authentication_backend=auth,
        title="ITKAM34 Billing",
        base_url="/admin",
    )
    for view in (UserAdmin, WalletAdmin, LedgerAdmin, ProductAdmin, ServiceAdmin,
                 NodeAdmin, AccountAdmin, UsageAdmin, TaskAdmin, PaymentAdmin):
        admin.add_view(view)
