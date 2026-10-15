import asyncio

from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response as StarletteResponse
from starlette.responses import RedirectResponse

from app.core import security
from app.db import SessionLocal, engine
from app.models import (
    Coupon, LedgerEntry, PaymentRequest, Product, ProvisioningTask,
    ServiceInstance, UsageSession, User, VpnAccount, VpnNode, Wallet,
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
    column_list = [Wallet.id, Wallet.user_id, Wallet.balance_minor, Wallet.promise_limit_minor]
    column_editable = [Wallet.balance_minor, Wallet.promise_limit_minor]
    can_edit = True
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

    @staticmethod
    def _pk_list(request: Request, pks) -> list:
        if pks is None:
            raw = request.query_params.get("pks", "")
        elif isinstance(pks, (list, tuple)):
            raw = ",".join(str(x) for x in pks)
        else:
            raw = str(pks)
        return [int(x) for x in raw.split(",") if x.strip().isdigit()]

    @action(name="approve", label="Одобрить и зачислить",
            confirmation_message="Зачислить сумму на кошелёк клиента?")
    async def approve(self, request: Request, pks=None):
        ids = self._pk_list(request, pks)

        def _sync():
            db = SessionLocal()
            try:
                for pid in ids:
                    pr = db.get(PaymentRequest, pid)
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
    async def reject(self, request: Request, pks=None):
        ids = self._pk_list(request, pks)

        def _sync():
            db = SessionLocal()
            try:
                for pid in ids:
                    pr = db.get(PaymentRequest, pid)
                    if pr is not None and pr.status == "pending":
                        pr.status = "rejected"
                db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_sync)
        return self._redirect_list(request)


_QUICK_LINKS_HTML = """<div id="admin-quicklinks" style="position:fixed;bottom:0;left:0;right:0;background:#0d1117;border-top:2px solid #238636;padding:8px 16px;z-index:9999;font-family:sans-serif;font-size:14px">
<a href="/admin-ops/" style="color:#3fb950;font-weight:700;margin-right:14px;text-decoration:none">⚡ Быстрые операции</a>
<a href="/admin-ops/nodes/import" style="color:#58a6ff;margin-right:14px;text-decoration:none">Импорт ноды</a>
<a href="/admin-ops/tariffs" style="color:#58a6ff;margin-right:14px;text-decoration:none">Тарифы</a>
<a href="/admin-ops/tickets" style="color:#58a6ff;margin-right:14px;text-decoration:none">Тикеты</a>
<a href="/admin-ops/passwords" style="color:#58a6ff;margin-right:14px;text-decoration:none">Пароли</a>
<a href="/admin-ops/coupons" style="color:#58a6ff;margin-right:14px;text-decoration:none">🎟 Купоны</a>
<a href="/admin-help" style="color:#58a6ff;text-decoration:none">📚 База знаний</a>
</div>"""



_ADMIN_CSS = """<style id="admin-redesign-css">
:root{--tblr-primary:#16a34a;--tblr-primary-rgb:22,163,74;--tblr-link-color:#16a34a;--tblr-body-color:#0f172a}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#f6f8fb;font-size:14px}
.navbar-vertical,.navbar.navbar-dark,.navbar[class*="bg-dark"]{background:#0f172a!important;border-right:1px solid #1e293b}
.navbar-vertical .nav-link{color:#cbd5e1;border-radius:10px;margin:2px 8px;font-size:14px}
.navbar-vertical .nav-link:hover{background:rgba(255,255,255,.08);color:#fff}
.navbar-vertical .nav-link.active{background:rgba(22,163,74,.18)!important;color:#4ade80!important}
.navbar-vertical .nav-item-header{color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin:12px 16px 4px}
.card{border:none!important;border-radius:16px!important;box-shadow:0 6px 20px rgba(15,23,42,.06)!important}
.card .card-header{background:#fff;border-bottom:1px solid #eef2f7;font-weight:700}
.btn-primary{background:#16a34a!important;border-color:#16a34a!important;color:#fff}
.btn-primary:hover{background:#15803d!important}
.btn-outline-primary{color:#16a34a!important;border-color:#86efac!important}
.btn-outline-primary:hover{background:#dcfce7!important;color:#14532d!important}
.btn-danger{background:#e11d48!important;border-color:#e11d48!important}
.table{font-size:14px}
.table thead th{background:#f8fafc;color:#64748b;font-weight:600;font-size:12px;text-transform:none;border-bottom:2px solid #e2e8f0}
.table tbody td{vertical-align:middle}
.badge.bg-primary{background:#16a34a!important}
a{color:#16a34a}
.dropdown-menu{border-radius:12px;border:1px solid #e2e8f0;box-shadow:0 10px 30px rgba(15,23,42,.12)}
.form-control,.form-select{border-radius:10px;border-color:#cbd5e1;font-size:14px}
.form-control:focus,.form-select:focus{border-color:#16a34a;box-shadow:0 0 0 3px rgba(22,163,74,.15)}
.page-title{font-weight:800}
#admin-quicklinks{border-top:2px solid #16a34a!important}
</style>"""



_ADMIN_JS = """<script id="admin-ru">
(function(){
  var D = {
    "Actions":"Действия","Logout":"Выйти","Login":"Вход","Username":"Логин","Password":"Пароль",
    "Submit":"Войти","Save":"Сохранить","Save and continue editing":"Сохранить и продолжить",
    "Save and add another":"Сохранить и добавить ещё","Delete":"Удалить","Edit":"Изменить",
    "Create":"Создать","Go Back":"Назад","Yes":"Да","No":"Нет","Cancel":"Отмена","OK":"ОК",
    "Search":"Поиск","Apply":"Применить","Clear":"Сбросить","Previous":"Назад","Next":"Вперёд",
    "Column":"Колонка","Value":"Значение","No items found":"Ничего не найдено",
    "Please select at least one item":"Выберите хотя бы одну запись",
    "Are you sure you want to delete this item?":"Удалить эту запись?",
    "Are you sure you want to delete selected items?":"Удалить выбранные записи?",
    "Are you sure you want to remove this item?":"Удалить эту запись?",
    "id":"№","email":"Email","role":"Роль","status":"Статус","created_at":"Создано",
    "updated_at":"Обновлено","user_id":"Пользователь","wallet_id":"Кошелёк",
    "balance_minor":"Баланс, коп","promise_limit_minor":"Обещанный платёж, коп",
    "amount_minor":"Сумма, коп","reason":"Назначение","entry_type":"Тип операции",
    "method":"Способ","processed_at":"Обработано","comment":"Комментарий",
    "code":"Код","name":"Название","service_type":"Тип услуги","unit":"Единица",
    "price_minor":"Цена, коп","active":"Активен","product_id":"Тариф",
    "node_id":"Нода","username":"Логин клиента","uuid":"UUID","protocol":"Протокол",
    "country":"Страна","api_kind":"Тип API","api_url":"Адрес API","endpoint_host":"Хост",
    "endpoint_port":"Порт","external_id":"Внешний ID","public_key":"Публичный ключ",
    "service_instance_id":"Услуга","vpn_account_id":"VPN-аккаунт","started_at":"Начало",
    "ended_at":"Окончание","last_heartbeat_at":"Последний сигнал","rx_bytes":"Принято, байт",
    "tx_bytes":"Передано, байт","charged_minutes":"Минут","cost_minor":"Стоимость, коп",
    "traffic_pending_bytes":"Трафик к списанию, байт","external_session_id":"Внешняя сессия",
    "entity_type":"Тип объекта","entity_id":"Объект","action":"Действие","attempts":"Попыток",
    "error":"Ошибка","result":"Результат","payload":"Данные","kind":"Тип",
    "max_activations":"Максимум активаций","activations_count":"Активировано",
    "expires_at":"Действует до","note":"Примечание","subject":"Тема",
    "author_role":"Автор","body":"Текст","ticket_id":"Тикет","secret_enc":"Секрет",
    "password_hash":"Пароль (хэш)","is_admin":"Админ","category":"Категория",
    "config":"Конфигурация","extra":"Доп. данные","sub_id":"ID подписки",
    "limit_ip":"Лимит IP","total_gb":"Лимит трафика","enable":"Включён",
    "Showing":"Показано","items":"записей","item":"запись"
  };
  var R = [
    [/Showing (\\d+) to (\\d+) of (\\d+) items?/, "Показано $1–$2 из $3"],
    [/^\\((\\d+) rows?\\)$/, "($1 строк)"],
    [/^(\\d+) items?$/, "$1 записей"]
  ];
  function tr(t){
    t = t.trim();
    if (D[t]) return D[t];
    for (var i=0;i<R.length;i++){ if (R[i][0].test(t)) return t.replace(R[i][0], R[i][1]); }
    return null;
  }
  function walk(node){
    if (node.nodeType === 3){
      var r = tr(node.nodeValue);
      if (r !== null) node.nodeValue = r;
    } else if (node.nodeType === 1 && !/^(SCRIPT|STYLE|INPUT|TEXTAREA|SELECT)$/.test(node.tagName)){
      for (var i=0;i<node.childNodes.length;i++) walk(node.childNodes[i]);
    }
  }
  function run(){
    walk(document.body);
    var ph = document.querySelectorAll('input[placeholder="Search"]');
    for (var i=0;i<ph.length;i++) ph[i].placeholder = "Поиск";
    var t = document.title;
    if (t.indexOf("Admin") === 0) document.title = t.replace("Admin", "Админка");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();
</script>"""


class AdminQuickLinksMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if not (path == "/admin" or path.startswith("/admin/")):
            return response
        if path.startswith("/admin-ops") or path.startswith("/admin-help"):
            return response
        ctype = response.headers.get("content-type", "")
        if "text/html" not in ctype:
            return response
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        html = b"".join(chunks).decode("utf-8", errors="ignore")
        media = ctype.split(";")[0]
        if "</head>" in html and "admin-redesign-css" not in html:
            html = html.replace("</head>", _ADMIN_CSS + "\n</head>", 1)
        if "</body>" in html and "admin-quicklinks" not in html:
            html = html.replace("</body>", _QUICK_LINKS_HTML + "\n" + _ADMIN_JS + "\n</body>")
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return StarletteResponse(content=html, status_code=response.status_code,
                                 headers=headers, media_type=media)


class CouponAdmin(ModelView, model=Coupon):
    column_list = [Coupon.id, Coupon.code, Coupon.kind, Coupon.amount_minor,
                   Coupon.max_activations, Coupon.activations_count, Coupon.active,
                   Coupon.expires_at]
    column_editable = [Coupon.active, Coupon.max_activations, Coupon.expires_at, Coupon.note]
    name = "Код (купон/промо/сертификат)"
    name_plural = "Купоны, промокоды, сертификаты"
    icon = "fa fa-ticket"


def setup_admin(app, secret_key: str = ""):
    if not any(getattr(m, "cls", None) is AdminQuickLinksMiddleware for m in app.user_middleware):
        app.add_middleware(AdminQuickLinksMiddleware)
    if not any(getattr(m, "cls", None) is SessionMiddleware for m in app.user_middleware):
        app.add_middleware(SessionMiddleware, secret_key=secret_key or "itkam34-billing-sessions")
    admin = Admin(
        app, engine,
        authentication_backend=AdminAuth(secret_key or "itkam34-billing-sessions"),
        title="ITKAM34 Billing",
        base_url="/admin",
    )
    for view in (UserAdmin, WalletAdmin, LedgerAdmin, ProductAdmin, ServiceAdmin,
                 NodeAdmin, AccountAdmin, UsageAdmin, TaskAdmin, PaymentAdmin, CouponAdmin):
        admin.add_view(view)
    return admin
