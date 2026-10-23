import time
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.vpn import get_adapter
from app.core.tz import now as tz_now
from app.core import security
from app.db import get_db
from app.models import PaymentMethod as _PM
from app.models import (
    LedgerEntry, PaymentRequest, Product, ServiceInstance, SupportTicket,
    TicketMessage, User, VpnAccount, VpnNode,
)
from app.services import ledger
from app.services.payments import approve_payreq
from app.core.notifications import notify_admin
from app.services.provisioning import enqueue_task
from app.core.settings_svc import get_setting as _gs144

router = APIRouter(prefix="/lk", tags=["lk"])
public_router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="app/ui/templates")

SESSION_LONG = 30 * 24 * 3600
SESSION_SHORT = 12 * 3600

RU_STATUS = {
    "active": "активна", "suspended": "приостановлена", "provisioning": "выдаётся",
    "pending": "ожидает", "terminated": "завершена", "closed": "закрыта",
}
RU_PAYREQ = {"pending": "на проверке", "approved": "зачислено", "rejected": "отклонено"}
REASON_RU = {
    "topup_cashback": "Бонус за пополнение",
    "referral_reward": "Награда за друга",
    "promo_code": "Промокод",
    "gift_certificate": "Подарочный сертификат",
    "coupon": "Купон",
    "vpn_usage_second": "Плата за использование (посекундно)",
    "vpn_usage_minute": "Плата за использование (поминутно)",
    "vpn_traffic_gb": "Плата за трафик (ГиБ)",
    "payment_cash": "Пополнение: наличные",
    "payment_transfer": "Пополнение: перевод на карту",
    "payment_other": "Пополнение: другое",
    "service_activation_month": "Активация месячного тарифа",
    "service_activation_one_time": "Разовая оплата услуги",
}


def _ru_reason(r: str) -> str:
    if r in REASON_RU:
        return REASON_RU[r]
    if r.startswith("vpn_usage_"):
        return "Плата за использование"
    if r.startswith("payment_"):
        return "Пополнение баланса"
    if r.startswith("service_activation"):
        return "Активация тарифа"
    return r


TYPE_RU = {
    "vpn": "Защищённый канал", "vps": "Сервер", "cctv": "Видеонаблюдение",
    "hosting": "Хостинг", "storage": "Хранилище", "mail": "Почта",
}
templates.env.filters["ru_type"] = lambda t: TYPE_RU.get((t or "").lower(), t)
templates.env.filters["ru_reason"] = _ru_reason
templates.env.filters["ru_status"] = lambda s: RU_STATUS.get(s, s)
templates.env.filters["ru_payreq"] = lambda s: RU_PAYREQ.get(s, s)
from app.core import labels as _labels
RU_METHOD = _labels.METHOD_RU
def _ru_method(m: str) -> str:
    return _labels.ru_method(m)
templates.env.filters["ru_method"] = _ru_method

class _Friendly:
    """Прозрачная обёртка: подменяет указанные поля на человеческие названия."""
    def __init__(self, obj, maps):
        object.__setattr__(self, "_o", obj)
        object.__setattr__(self, "_m", maps)
    def __getattr__(self, k):
        v = getattr(self._o, k)
        f = self._m.get(k)
        return f(v) if f else v

_ENTRY_MAP = {"reason": _labels.ru_reason}
_PAYREQ_MAP = {"method": _labels.ru_method}

TOPUP_METHODS = [
    ("transfer", "Перевод на карту"),
    ("cash", "Наличные"),
    ("other", "Другое"),
]
TOPUP_NOTES = {
    "transfer": "Переведите сумму на карту Сбербанк по номеру +7 000 000-00-00 (Имя Фамилия). "
                "В комментарии к переводу укажите ваш email — так мы быстрее найдём платёж.",
    "cash": "Передайте наличные администратору; в комментарии укажите, когда и где.",
    "other": "Опишите в комментарии способ оплаты — администратор свяжется с вами.",
}


MAX_TOPUP_MINOR = 100_000_000  # 1 000 000 ₽


def parse_rub(raw: str) -> int:
    """'12,5' -> 1250 копеек. Без float; 0 при любой ошибке/нечисле/переполнении."""
    try:
        value = Decimal((raw or "").strip().replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return 0
    if not value.is_finite() or value <= 0:
        return 0
    minor = int((value * 100).to_integral_value())
    return minor if 0 < minor <= MAX_TOPUP_MINOR else 0


def _client_methods(db):
    pm = db.execute(select(_PM).where(_PM.active.is_(True), _PM.client_visible.is_(True)).order_by(_PM.sort_order)).scalars().all()
    return [(m.code, m.title) for m in pm] or [(c, l) for c, l in TOPUP_METHODS if c != "cash"]


def _client_notes(db):
    pm = db.execute(select(_PM).where(_PM.active.is_(True), _PM.client_visible.is_(True)).order_by(_PM.sort_order)).scalars().all()
    return {m.code: m.instructions for m in pm} or {k: v for k, v in TOPUP_NOTES.items() if k != "cash"}


def _session_alive(request: Request) -> bool:
    exp = request.session.get("exp")
    if not exp:
        return False
    if time.time() > int(exp):
        request.session.clear()
        return False
    return True


def _current_user(db: Session, request: Request):
    if not _session_alive(request):
        return None
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, int(uid))
    if user is None or user.status not in ("active", "pending_verify"):  # заблокированного выкидываем сразу
        request.session.clear()
        return None
    return user


@public_router.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    products = db.execute(
        select(Product).where(Product.active.is_(True))
    ).scalars().all()
    user = _current_user(db, request)
    return templates.TemplateResponse(
        request, "lk/landing.html", {"products": products, "user": user}
    )


@public_router.get("/sub/{sub_id}")
def public_sub(sub_id: str, request: Request, db: Session = Depends(get_db)):
    import base64
    from fastapi.responses import Response
    sid = (sub_id or "").strip()
    target = None
    for a in db.execute(select(VpnAccount).where(VpnAccount.status != "deleted")).scalars().all():
        ex = a.extra or {}
        if ex.get("sub_id") == sid or (a.username or "").split("@")[0] == sid:
            target = a
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    node = db.get(VpnNode, target.node_id)
    link = ""
    if node is not None:
        try:
            link = (get_adapter(node).render_config(db, target).get("link") or "")
        except Exception:
            link = ""
    if not link and target.uuid and node is not None:
        from urllib.parse import urlparse
        ex = node.extra or {}
        host = node.endpoint_host or ex.get("endpoint_host") or urlparse(node.api_url or "").hostname or ""
        port = node.endpoint_port or ex.get("inbound_port") or ex.get("endpoint_port") or 443
        link = f"vless://{target.uuid}@{host}:{port}?security=none&encryption=none&type=tcp#{node.code or 'vpn'}"
    body = base64.b64encode((link or "").encode()).decode()
    return Response(content=body, media_type="text/plain; charset=utf-8",
                    headers={"profile-update-interval": "12",
                             "subscription-userinfo": "upload=0; download=0; total=0; expire=0"})


@public_router.get("/assets/theme.css")
def theme_css():
    from fastapi.responses import Response
    import os as _os
    path = _os.path.join("app", "ui", "theme.css")
    try:
        css = open(path).read()
    except OSError:
        css = ""
    return Response(content=css, media_type="text/css", headers={"Cache-Control": "public, max-age=300"})


@public_router.get("/legal/{name}", response_class=HTMLResponse)
def legal_page(name: str, request: Request, db: Session = Depends(get_db)):
    import os as _os
    if name not in ("offer", "terms", "privacy"):
        raise HTTPException(status_code=404)
    path = _os.path.join("docs", "legal", f"{name}.md")
    from app.core.settings_svc import get_setting as _gsdoc
    md = _gsdoc(db, "doc_" + name, "") or ""
    if not md:
        try:
            md = open(path).read()
        except OSError:
            md = "Документ готовится к публикации."
    out = []
    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    body = "".join(out)
    return HTMLResponse("<!doctype html><html lang=ru><head><meta charset=utf-8>"
                        "<title>Документы · ITKAM34</title>"
                        "<link rel=stylesheet href=/assets/theme.css></head><body>"
                        f"<div class=legal-links><a href='/'>← На главную</a></div>"
                        f"<div class=card>{body}</div></body></html>")


@public_router.get("/invest", response_class=HTMLResponse)
def invest_page(request: Request, error: str = "", ok: str = "",
                db: Session = Depends(get_db)):
    price = int(_gs144(db, "invest_share_price_minor", "1000000") or 1000000)
    return templates.TemplateResponse(request, "lk/invest.html",
                                      {"error": error, "ok": ok, "share_price": price / 100})


@public_router.post("/invest")
def invest_login(request: Request, email: str = Form(), password: str = Form(),
                 db: Session = Depends(get_db)):
    from app.models import PartnerShare
    email = security.normalize_email(email)
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if user is None or not security.verify_password(password, user.password_hash) or user.status != "active":
        return RedirectResponse("/invest?error=1", status_code=303)
    partner = db.execute(select(PartnerShare).where(PartnerShare.user_id == user.id,
                                                    PartnerShare.status == "active")).scalars().first()
    if partner is None and user.role != "admin":
        return RedirectResponse("/invest?error=2", status_code=303)
    request.session["uid"] = user.id
    import time as _t
    request.session["exp"] = int(_t.time()) + SESSION_LONG
    return RedirectResponse("/lk/", status_code=303)


def _ip_risk(db, ip: str) -> bool:
    """Подозрительный IP: много регистраций за сутки / были блокировки / автоподтверждение уже использовали."""
    if not ip:
        return False
    from app.core.tz import now as _now
    day0 = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    cnt = len(db.execute(select(User).where(User.register_ip == ip, User.created_at >= day0)).scalars().all())
    if cnt >= 3:
        return True
    bad = db.execute(select(User).where(User.register_ip == ip, User.status == "blocked")).scalars().first()
    if bad is not None:
        return True
    used = db.execute(select(User).where(User.register_ip == ip, User.auto_used.is_(True))).scalars().first()
    return used is not None


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, error: str = "", db: Session = Depends(get_db)):
    import random
    a, b = random.randint(2, 9), random.randint(2, 9)
    request.session["captcha"] = a + b
    ip = request.client.host if request.client else ""
    risk = _ip_risk(db, ip)
    request.session["reg_risk"] = "1" if risk else ""
    return templates.TemplateResponse(request, "lk/register.html",
                                      {"error": error, "ref": request.query_params.get("ref", ""),
                                       "captcha_q": f"{a} + {b}", "risk": risk})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(),
    password: str = Form(min_length=8),
    ref: str = Form(""),
    captcha: str = Form(""),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else ""
    want = request.session.get("captcha")
    request.session.pop("captcha", None)
    risk = request.session.pop("reg_risk", "") == "1" or _ip_risk(db, ip)
    try:
        got = int((captcha or "").strip())
    except ValueError:
        got = None
    if want is None or got != want:
        return RedirectResponse("/lk/register?error=5", status_code=303)
    email = security.normalize_email(email)
    if "@" not in email or len(email) > 254:
        return RedirectResponse("/lk/register?error=1", status_code=303)
    if risk:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            return RedirectResponse("/lk/register?error=8", status_code=303)
    exists = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if exists is not None:
        return RedirectResponse("/lk/register?error=2", status_code=303)
    import uuid as _uuid
    referred = None
    if ref.strip():
        rrow = db.execute(select(User).where(User.referral_code == ref.strip())).scalar_one_or_none()
        referred = rrow.id if rrow is not None else None
    status = "pending_verify" if risk else "active"
    user = User(email=email, password_hash=security.hash_password(password),
                referral_code=_uuid.uuid4().hex[:10], referred_by=referred,
                register_ip=ip or None, phone=phone.strip() or None, status=status)
    db.add(user)
    try:
        db.flush()
        ledger.get_wallet(db, user.id)
        if risk:
            notify_admin(db, f"🕵 Регистрация на проверку: {email}, телефон {phone.strip() or 'не указан'}, IP {ip}")
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/lk/register?error=2", status_code=303)
    return RedirectResponse("/lk/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if _current_user(db, request) is not None:
        return RedirectResponse("/lk/", status_code=303)
    return templates.TemplateResponse(request, "lk/login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    remember: str = Form("on"),
    db: Session = Depends(get_db),
):
    email = security.normalize_email(email)
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if user is None or not security.verify_password(password, user.password_hash) \
            or user.status != "active":
        return templates.TemplateResponse(
            request, "lk/login.html",
            {"error": "Неверный email или пароль"}, status_code=401,
        )
    request.session["uid"] = user.id
    request.session["exp"] = int(time.time()) + (SESSION_LONG if remember == "on" else SESSION_SHORT)
    return RedirectResponse("/lk/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/lk/login", status_code=303)


def _own_service(db: Session, user: User, service_id: int) -> ServiceInstance:
    service = db.get(ServiceInstance, service_id)
    if service is None or service.user_id != user.id:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    if user.role == "cashier":
        return RedirectResponse("/lk/kassa", status_code=303)
    wallet = ledger.get_wallet(db, user.id)
    entries = db.execute(
        select(LedgerEntry)
        .where(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.id.desc())
        .limit(20)
    ).scalars().all()
    services = db.execute(
        select(ServiceInstance).where(ServiceInstance.user_id == user.id)
    ).scalars().all()
    payreqs = db.execute(
        select(PaymentRequest)
        .where(PaymentRequest.user_id == user.id)
        .order_by(PaymentRequest.id.desc())
        .limit(10)
    ).scalars().all()
    return templates.TemplateResponse(request, "lk/dashboard.html", {
        "user": user, "wallet": wallet,
        "entries": [_Friendly(e, _ENTRY_MAP) for e in entries],
        "pending_verify": user.status == "pending_verify",
        "invest_ads": _gs144(db, "invest_ads_enabled", "1") == "1",
        "my_div": _my_div_summary(db, user),
        "services": services,
        "payreqs": [_Friendly(pq, _PAYREQ_MAP) for pq in payreqs],
        "methods": _client_methods(db), "notes": _client_notes(db),
    })


@router.post("/topup")
def topup(
    request: Request,
    amount: str = Form(),
    method: str = Form(),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    amount_minor = parse_rub(amount)
    if amount_minor <= 0:
        return RedirectResponse("/lk/", status_code=303)
    if method not in dict(_client_methods(db)):
        method = "other"
    wallet = ledger.get_wallet(db, user.id)
    pr = PaymentRequest(
        user_id=user.id, amount_minor=amount_minor, method=method,
        comment=comment.strip() or None, status="pending",
    )
    db.add(pr)
    db.flush()
    # Одноразовый доверительный лимит: первое пополнение до 500 ₽ зачисляется сразу.
    from app.core.settings_svc import get_setting as _gs
    _lim = wallet.auto_approve_limit_minor
    AUTO_APPROVE_LIMIT = int(_lim) if _lim is not None else int(_gs(db, "auto_approve_limit_minor", "50000"))
    _enabled = _gs(db, "auto_approve_enabled", "1") == "1"
    _max_uses = wallet.auto_approve_max_uses or 1
    if user.status != "active":
        _enabled = False
    ip_used = None
    if user.register_ip:
        ip_used = db.execute(select(User).where(User.register_ip == user.register_ip, User.auto_used.is_(True), User.id != user.id)).scalars().first()
    if ip_used is not None:
        _enabled = False
    if _enabled and (wallet.auto_approved_count or 0) < _max_uses and amount_minor <= AUTO_APPROVE_LIMIT:
        approve_payreq(db, pr, actor_email="авто (доверительный лимит)")
        wallet.auto_approved_count = (wallet.auto_approved_count or 0) + 1
        user.auto_used = True
        notify_admin(db, f"🤖 Автоподтверждение (1 раз): #{pr.id} {(amount_minor/100):.0f} ₽ от {user.email}")
    else:
        notify_admin(db, f"💳 Новая заявка #{pr.id}: {(amount_minor/100):.0f} ₽ ({method}) от {user.email}")
    db.commit()
    return RedirectResponse("/lk/", status_code=303)



@router.post("/topup/{payreq_id}/cancel")
def topup_cancel(payreq_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    pr = db.get(PaymentRequest, payreq_id)
    if pr is not None and pr.user_id == user.id and pr.status == "pending":
        db.delete(pr)
        db.commit()
    return RedirectResponse("/lk/", status_code=303)

@router.get("/order", response_class=HTMLResponse)
def order_page(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    products = db.execute(
        select(Product).where(Product.active.is_(True))
    ).scalars().all()
    nodes = db.execute(
        select(VpnNode).where(VpnNode.active.is_(True))
    ).scalars().all()
    pre = request.query_params.get("product", "")
    return templates.TemplateResponse(request, "lk/order.html", {
        "user": user, "products": products, "nodes": nodes, "pre": pre,
    })


@router.post("/order")
def order_create(
    request: Request,
    product_id: int = Form(),
    node_id: int = Form(0),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    if user.status != "active":
        return RedirectResponse("/lk/", status_code=303)
    product = db.get(Product, product_id)
    if product is None or not product.active:
        raise HTTPException(status_code=404, detail="Product not found")

    node = None
    if product.service_type == "vpn":
        proto = product.config.get("protocol")
        if node_id:
            candidate = db.get(VpnNode, node_id)
            if candidate is not None and candidate.active and candidate.protocol == proto:
                node = candidate
        if node is None:
            node = db.execute(
                select(VpnNode).where(
                    VpnNode.active.is_(True), VpnNode.protocol == proto
                )
            ).scalars().first()
        if node is None:
            return RedirectResponse("/lk/order", status_code=303)

    service = ServiceInstance(
        user_id=user.id,
        product_id=product.id,
        name=name.strip() or product.name,
        status="provisioning" if node else "pending",
        config={"node_id": node.id} if node else {},
    )
    db.add(service)
    db.flush()
    if node is not None:
        enqueue_task(db, "service_instance", service.id, "create")
    db.commit()
    return RedirectResponse("/lk/", status_code=303)


@router.post("/services/{service_id}/delete")
def service_delete(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
    task = enqueue_task(db, "service_instance", service.id, "delete")
    db.commit()
    from app.services.provisioning import process_task_now
    process_task_now(db, task.id)
    db.commit()
    return RedirectResponse("/lk/", status_code=303)



@router.get("/services/status.json")
def services_status_json(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    rows = db.execute(
        select(ServiceInstance).where(ServiceInstance.user_id == user.id)
    ).scalars().all()
    return [
        {"id": s.id, "status": s.status, "ru": RU_STATUS.get(s.status, s.status)}
        for s in rows
    ]


@router.get("/services/{service_id}/status.json")
def service_status_json(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    return {
        "id": service.id,
        "status": service.status,
        "ru": RU_STATUS.get(service.status, service.status),
        "has_link": account is not None and account.status != "deleted" and service.status == "active",
    }


@router.get("/services/{service_id}/config", response_class=HTMLResponse)
def service_config(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    service = _own_service(db, user, service_id)
    account = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalar_one_or_none()
    if account is None and service.status in ("active", "provisioning", "suspended"):
        from app.models import ProvisioningTask as _PT
        open_task = db.execute(
            select(_PT).where(_PT.entity_type == "service_instance", _PT.entity_id == service.id,
                              _PT.action == "create", _PT.status.in_(("pending", "running")))
        ).scalars().first()
        if open_task is None and (service.config or {}).get("node_id"):
            enqueue_task(db, "service_instance", service.id, "create")
            db.commit()
            open_task = db.execute(
                select(_PT).where(_PT.entity_type == "service_instance", _PT.entity_id == service.id,
                                  _PT.action == "create", _PT.status.in_(("pending", "running")))
            ).scalars().first()
        if open_task is None:
            open_task = db.execute(
                select(_PT).where(_PT.entity_type == "service_instance", _PT.entity_id == service.id,
                                  _PT.action == "create", _PT.status == "error")
                .order_by(_PT.id.desc())
            ).scalars().first()
        if open_task is not None and open_task.status in ("pending", "error"):
            from app.services.provisioning import process_task_now
            try:
                process_task_now(db, open_task.id)
                db.commit()
            except Exception:
                db.rollback()
            account = db.execute(
                select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
            ).scalar_one_or_none()
    task_status = task_error = None
    task_status = task_error = None
    link = sub_url = conf = None
    if account is not None and account.status != "deleted" and (not account.uuid or not account.secret_enc):
        task_status, task_error = "broken", "аккаунт повреждён — нажми «Перевыпустить ключ»"
    if account is not None:
        node = db.get(VpnNode, account.node_id)
        if node is not None and account.status != "deleted":
            try:
                cfg = get_adapter(node).render_config(db, account)
            except Exception as exc:
                cfg = {}
                task_status, task_error = "render_error", str(exc)[:200]
            link, sub_url, conf = cfg.get("link"), cfg.get("subscription_url"), cfg.get("config_text")
    if account is not None and account.status != "deleted" and link is None and account.uuid:
        _nd = db.get(VpnNode, account.node_id)
        if _nd is not None:
            from urllib.parse import urlparse
            _ex = _nd.extra or {}
            _host = (_nd.endpoint_host or _ex.get("endpoint_host")
                     or urlparse(_nd.api_url or "").hostname or "")
            _port = (_nd.endpoint_port or _ex.get("inbound_port")
                     or _ex.get("endpoint_port") or 443)
            if _host:
                _enc = _ex.get("encryption", "none")
                _sec = _ex.get("security", "none")
                _typ = _ex.get("network", "tcp")
                link = (f"vless://{account.uuid}@{_host}:{_port}"
                        f"?security={_sec}&encryption={_enc}&type={_typ}#{_nd.code or 'vpn'}")
                task_status, task_error = "fallback", "ссылка собрана напрямую из данных ноды"
    _sid = (account.extra or {}).get("sub_id") if account is not None else None
    if _sid:
        _nd2 = db.get(VpnNode, account.node_id) if account is not None else None
        from urllib.parse import urlparse as _up2
        _ex2 = (_nd2.extra or {}) if _nd2 is not None else {}
        _h2 = (_ex2.get("sub_domain") or (_nd2.endpoint_host if _nd2 is not None else None)
               or _up2((_nd2.api_url if _nd2 is not None else "") or "").hostname or "")
        _p2 = _ex2.get("sub_port") or 2096
        _pa2 = _ex2.get("sub_path") or "/sub/"
        sub_url = f"https://{_h2}:{_p2}{_pa2}{_sid}"
    elif account is not None:
        _s0 = (account.username or "").split("@")[0]
        if _s0:
            sub_url = f"{request.url.scheme}://{request.headers.get('host')}/sub/{_s0}"
    if sub_url:
        link = sub_url
        conf = None
    # QR всегда кодирует подписку, даже если link есть
    if account is not None and link is None and account.uuid:
        _nd = db.get(VpnNode, account.node_id)
        if _nd is not None:
            from urllib.parse import urlparse
            _ex = _nd.extra or {}
            _host = (_nd.endpoint_host or _ex.get("endpoint_host")
                     or urlparse(_nd.api_url or "").hostname or "")
            _port = (_nd.endpoint_port or _ex.get("inbound_port")
                     or _ex.get("endpoint_port") or 443)
            if _host:
                _enc = _ex.get("encryption", "none")
                _sec = _ex.get("security", "none")
                _typ = _ex.get("network", "tcp")
                link = (f"vless://{account.uuid}@{_host}:{_port}"
                        f"?security={_sec}&encryption={_enc}&type={_typ}#{_nd.code or 'vpn'}")
    if account is not None and link is None and task_status is None:
        task_status, task_error = "debug", f"uuid={bool(account.uuid)} node={account.node_id}"
    if account is None:
        from app.models import ProvisioningTask as _PT2
        lt = db.execute(
            select(_PT2).where(_PT2.entity_type == "service_instance", _PT2.entity_id == service.id,
                               _PT2.action == "create").order_by(_PT2.id.desc())
        ).scalars().first()
        if lt is not None:
            task_status, task_error = lt.status, lt.error
    qr_svg = ""
    qr_target = sub_url or link
    if qr_target:
        try:
            import qrcode
            from qrcode.image.svg import SvgPathImage
            qr_svg = qrcode.make(qr_target, image_factory=SvgPathImage).to_string(encoding="unicode")
        except Exception:
            qr_svg = ""
    return templates.TemplateResponse(request, "lk/config.html", {
        "user": user, "service": service, "link": link, "sub_url": sub_url,
        "conf": conf, "qr_svg": qr_svg, "task_status": task_status, "task_error": task_error,
    })


@router.post("/services/{service_id}/suspend")
def service_suspend(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
    if service.status != "active":
        return RedirectResponse("/lk/", status_code=303)
    service.status = "suspended"
    enqueue_task(db, "service_instance", service.id, "suspend")
    db.commit()
    return RedirectResponse("/lk/", status_code=303)


@router.post("/services/{service_id}/resume")
def service_resume(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
    if service.status != "suspended":
        return RedirectResponse("/lk/", status_code=303)
    wallet = ledger.get_wallet(db, user.id)
    product = db.get(Product, service.product_id)
    min_balance = product.price_minor if product is not None else 1
    promise = getattr(wallet, 'promise_limit_minor', 0) or 0
    if wallet.balance_minor + promise <= 0 or wallet.balance_minor + promise < min_balance:
        raise HTTPException(status_code=402, detail="Top up balance first")
    service.status = "active"
    enqueue_task(db, "service_instance", service.id, "resume")
    db.commit()
    return RedirectResponse("/lk/", status_code=303)


# ================= Тикеты поддержки =================

@router.get("/tickets", response_class=HTMLResponse)
def tickets_list(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    tickets = db.execute(
        select(SupportTicket).where(SupportTicket.user_id == user.id)
        .order_by(SupportTicket.id.desc())
    ).scalars().all()
    return templates.TemplateResponse(request, "lk/tickets.html", {"user": user, "tickets": tickets})


@router.get("/tickets/new", response_class=HTMLResponse)
def ticket_new_page(request: Request):
    return templates.TemplateResponse(request, "lk/ticket_new.html", {"error": None})


@router.post("/tickets/new")
def ticket_new(request: Request, subject: str = Form(), body: str = Form(), db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    ticket = SupportTicket(user_id=user.id, subject=subject.strip()[:200] or "Обращение", status="open")
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_role="client", body=body.strip()))
    db.commit()
    return RedirectResponse(f"/lk/tickets/{ticket.id}", status_code=303)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_view(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None or ticket.user_id != user.id:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "lk/ticket_view.html", {"user": user, "ticket": ticket})


@router.post("/tickets/{ticket_id}/reply")
def ticket_reply(ticket_id: int, request: Request, body: str = Form(), db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None or ticket.user_id != user.id:
        raise HTTPException(status_code=404)
    if ticket.status != "closed":
        db.add(TicketMessage(ticket_id=ticket.id, author_role="client", body=body.strip()))
        ticket.status = "open"
        ticket.updated_at = tz_now()
        db.commit()
    return RedirectResponse(f"/lk/tickets/{ticket.id}", status_code=303)


# ================= Коды: купоны / промокоды / сертификаты =================

REASON_BY_KIND = {"promo": "promo_code", "gift": "gift_certificate", "coupon": "coupon"}


@router.post("/coupon")
def coupon_activate(request: Request, code: str = Form(), db: Session = Depends(get_db)):
    from app.models import Coupon, CouponActivation
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    code_clean = (code or "").strip().upper()
    coupon = db.execute(
        select(Coupon).where(Coupon.code == code_clean, Coupon.active.is_(True))
    ).scalar_one_or_none()
    error = None
    if coupon is None:
        error = "Код не найден или недействителен"
    elif coupon.expires_at is not None and coupon.expires_at < tz_now():
        error = "Срок действия кода истёк"
    elif coupon.activations_count >= coupon.max_activations:
        error = "Код уже использован полностью"
    else:
        already = db.execute(
            select(CouponActivation).where(
                CouponActivation.coupon_id == coupon.id, CouponActivation.user_id == user.id
            )
        ).scalar_one_or_none()
        if already is not None:
            error = "Вы уже активировали этот код"
        else:
            wallet = ledger.get_wallet(db, user.id)
            ledger.credit(
                db, wallet, coupon.amount_minor,
                reason=REASON_BY_KIND.get(coupon.kind, "coupon"),
                entity_type="coupon", entity_id=coupon.id,
                idempotency_key=f"coupon:{coupon.id}:{user.id}",
            )
            coupon.activations_count += 1
            db.add(CouponActivation(coupon_id=coupon.id, user_id=user.id, amount_minor=coupon.amount_minor))
            db.commit()
            return templates.TemplateResponse(request, "lk/coupon_result.html", {
                "user": user, "ok": True,
                "message": f"Код активирован: на баланс зачислено {(coupon.amount_minor / 100):.2f} ₽",
            })
    return templates.TemplateResponse(request, "lk/coupon_result.html", {
        "user": user, "ok": False, "message": error or "Не удалось активировать код",
    }, status_code=400)


# ================= Касса (роль cashier и admin) =================

@router.get("/kassa", response_class=HTMLResponse)
def kassa_page(request: Request, error: str = "", ok: str = "", db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None or user.role not in ("cashier", "admin"):
        raise HTTPException(status_code=403)
    reqs = db.execute(
        select(PaymentRequest).where(PaymentRequest.status == "pending")
        .order_by(PaymentRequest.id.desc())
    ).scalars().all()
    clients = db.execute(
        select(User).where(User.role == "client", User.status == "active")
        .order_by(User.email)
    ).scalars().all()
    return templates.TemplateResponse(request, "lk/kassa.html", {
        "user": user, "reqs": [_Friendly(r, _PAYREQ_MAP) for r in reqs],
        "clients": clients, "error": error, "ok": ok})


@router.post("/kassa/intake")
def kassa_intake(request: Request, user_id: int = Form(0), email: str = Form(""),
                 amount: str = Form(""), db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None or user.role not in ("cashier", "admin"):
        raise HTTPException(status_code=403)
    from app.services.payments import approve_payreq
    client = db.get(User, user_id) if user_id else None
    if client is None and email.strip():
        client = db.execute(
            select(User).where(User.email == security.normalize_email(email))
        ).scalar_one_or_none()
    if client is None:
        return RedirectResponse("/lk/kassa?error=1", status_code=303)
    amount_minor = parse_rub(amount)
    if amount_minor <= 0:
        return RedirectResponse("/lk/kassa?error=2", status_code=303)
    pr = PaymentRequest(user_id=client.id, amount_minor=amount_minor, method="cash",
                        comment="принято в кассе", status="pending")
    db.add(pr)
    db.flush()
    approve_payreq(db, pr, actor_email=f"касса: {user.email}")
    db.commit()
    return RedirectResponse(f"/lk/kassa?ok={amount_minor / 100:.2f}", status_code=303)


@router.get("/kassa/guide", response_class=HTMLResponse)
def kassa_guide(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None or user.role not in ("cashier", "admin"):
        raise HTTPException(status_code=403)
    return templates.TemplateResponse(request, "lk/kassa_guide.html", {"user": user})


@router.post("/kassa/{pid}/approve")
def kassa_approve(pid: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None or user.role not in ("cashier", "admin"):
        raise HTTPException(status_code=403)
    pr = db.get(PaymentRequest, pid)
    if pr is not None and pr.status == "pending" and pr.method == "cash":
        from app.services.payments import approve_payreq
        approve_payreq(db, pr, actor_email=f"касса: {user.email}")
        db.commit()
    return RedirectResponse("/lk/kassa", status_code=303)


@router.post("/kassa/{pid}/reject")
def kassa_reject(pid: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None or user.role not in ("cashier", "admin"):
        raise HTTPException(status_code=403)
    pr = db.get(PaymentRequest, pid)
    if pr is not None and pr.status == "pending" and pr.method == "cash":
        pr.status = "rejected"
        db.commit()
    return RedirectResponse("/lk/kassa", status_code=303)


@router.post("/services/{service_id}/reissue")
def service_reissue(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
    accs = db.execute(
        select(VpnAccount).where(VpnAccount.service_instance_id == service.id)
    ).scalars().all()
    for a in accs:
        db.delete(a)
    db.flush()
    enqueue_task(db, "service_instance", service.id, "create")
    db.commit()
    return RedirectResponse(f"/lk/services/{service.id}/config", status_code=303)


# ================= v137: Промо-центр и журнал (admin) =================

_PROMO_KEYS = [
    ("cashback_percent", "Кэшбэк с пополнения, % (0 — выключен)", "3"),
    ("cashback_min_minor", "Порог кэшбэка, копеек (100000 = 1000 ₽)", "100000"),
    ("referral_reward_minor", "Награда за реферала, копеек (0 — выключена)", "5000"),
    ("auto_approve_enabled", "Доверительный лимит: включён (1/0)", "1"),
    ("auto_approve_limit_minor", "Доверительный лимит, копеек (одноразово)", "50000"),
    ("auto_approve_max_uses", "Доверительный лимит: использований на кошелёк", "1"),
]

def _admin_user(db, request):
    user = _current_user(db, request)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user

@router.get("/promo", response_class=HTMLResponse)
def promo_page(request: Request, ok: str = "", db: Session = Depends(get_db)):
    user = _admin_user(db, request)
    from app.core.settings_svc import get_setting as _gs
    vals = {k: (_gs(db, k, d) or d) for k, _, d in _PROMO_KEYS}
    return templates.TemplateResponse(request, "lk/promo.html",
                                      {"user": user, "keys": _PROMO_KEYS, "vals": vals, "ok": ok})

@router.post("/promo")
async def promo_save(request: Request, db: Session = Depends(get_db)):
    _admin_user(db, request)
    form = await request.form()
    from app.core.settings_svc import set_setting as _ss
    for key, _, d in _PROMO_KEYS:
        v = (form.get(key) or "").strip() or d
        try:
            if key == "auto_approve_enabled":
                v = "1" if v in ("1", "on", "true", "да") else "0"
            elif key == "cashback_percent":
                v = str(max(0, min(100, int(v))))
            elif key.endswith("_minor"):
                v = str(max(0, int(v)))
            elif key == "auto_approve_max_uses":
                v = str(max(1, int(v)))
        except ValueError:
            v = d
        _ss(db, key, v)
    db.commit()
    return RedirectResponse("/lk/promo?ok=1", status_code=303)

def _ledger_filter(db, days: int, kind: str):
    from datetime import timedelta
    cutoff = tz_now() - timedelta(days=days)
    q = select(LedgerEntry).where(LedgerEntry.created_at < cutoff)
    if kind == "usage":
        q = q.where(LedgerEntry.reason.like("vpn_usage_%"))
    elif kind == "debits":
        q = q.where(LedgerEntry.amount_minor < 0)
    return q

@router.get("/ledger-admin", response_class=HTMLResponse)
def ledger_admin(request: Request, days: str = "90", kind: str = "usage",
                 msg: str = "", db: Session = Depends(get_db)):
    user = _admin_user(db, request)
    d = max(1, int(days or 90))
    q = _ledger_filter(db, d, kind)
    cnt = db.execute(select(func.count()).select_from(LedgerEntry)
                     .where(q.whereclause)).scalar() or 0
    rows = db.execute(q.order_by(LedgerEntry.id.desc()).limit(300)).scalars().all()
    return templates.TemplateResponse(request, "lk/ledger_admin.html",
                                      {"user": user, "days": d, "kind": kind,
                                       "cnt": cnt, "rows": rows, "msg": msg})

@router.post("/ledger-admin/delete")
def ledger_admin_delete(request: Request, days: str = Form("90"),
                        kind: str = Form("usage"), confirm: str = Form(""),
                        db: Session = Depends(get_db)):
    _admin_user(db, request)
    if confirm.strip() != "УДАЛИТЬ":
        return RedirectResponse("/lk/ledger-admin?msg=no-confirm", status_code=303)
    from sqlalchemy import delete as sa_delete
    d = max(1, int(days or 90))
    q = _ledger_filter(db, d, kind)
    ids = [r.id for r in db.execute(q.order_by(LedgerEntry.id.asc())).scalars().all()][:50000]
    done = 0
    for i in range(0, len(ids), 1000):
        done += db.execute(sa_delete(LedgerEntry).where(LedgerEntry.id.in_(ids[i:i+1000]))).rowcount
    db.commit()
    return RedirectResponse(f"/lk/ledger-admin?msg=deleted-{done}", status_code=303)

from app.core.labels import finalize_human as _fh141
templates.env.finalize = _fh141


@router.get("/dividends", response_class=HTMLResponse)
def my_dividends(request: Request, msg: str = "", db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    from app.services import dividends as dv
    dv.ensure_tables()
    me = db.execute(select(dv.PartnerShare).where(dv.PartnerShare.user_id == user.id,
                                                  dv.PartnerShare.status == "active")).scalars().all()
    accruals, payouts = [], []
    if me:
        ids = [p.id for p in me]
        accruals = db.execute(select(dv.DividendAccrual).where(dv.DividendAccrual.partner_id.in_(ids))
                              .order_by(dv.DividendAccrual.id.desc()).limit(60)).scalars().all()
        payouts = db.execute(select(dv.PayoutRequest).where(dv.PayoutRequest.partner_id.in_(ids))
                             .order_by(dv.PayoutRequest.id.desc()).limit(20)).scalars().all()
    return templates.TemplateResponse(request, "lk/dividends.html",
                                      {"user": user, "me": me, "accruals": accruals,
                                       "payouts": payouts, "msg": msg})

@router.post("/dividends/payout")
def my_dividend_payout(request: Request, amount: str = Form(""), requisites: str = Form(""),
                       db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        return RedirectResponse("/lk/login", status_code=303)
    from app.services import dividends as dv
    dv.ensure_tables()
    partner = db.execute(select(dv.PartnerShare).where(dv.PartnerShare.user_id == user.id,
                                                       dv.PartnerShare.status == "active")).scalars().first()
    if partner is None:
        return RedirectResponse("/lk/dividends?msg=not-partner", status_code=303)
    minor = parse_rub(amount)
    wallet = ledger.get_wallet(db, user.id)
    if minor <= 0 or minor > (wallet.balance_minor or 0):
        return RedirectResponse("/lk/dividends?msg=bad-amount", status_code=303)
    db.add(dv.PayoutRequest(partner_id=partner.id, amount_minor=minor,
                            requisites=requisites.strip()[:300]))
    db.commit()
    return RedirectResponse("/lk/dividends?msg=request-ok", status_code=303)


def _my_div_summary(db, user):
    from app.services import dividends as dv
    try:
        dv.ensure_tables()
        me = db.execute(select(dv.PartnerShare).where(
            dv.PartnerShare.user_id == user.id,
            dv.PartnerShare.status == "active")).scalars().first()
        if me is None:
            return None
        rows = db.execute(select(dv.DividendAccrual).where(
            dv.DividendAccrual.partner_id == me.id)).scalars().all()
        last = rows[-1] if rows else None
        return {"share": me.share_percent,
                "last": (last.amount_minor if last else 0),
                "total": sum(a.amount_minor or 0 for a in rows)}
    except Exception:
        return None

def _md_page146(path: str, title: str):
    try:
        md = open(path).read()
    except OSError:
        md = "Документ готовится к публикации."
    return _md_page146_text(md, title)

def _md_page146_text(md: str, title: str):
    out = []
    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            out.append("<h2>" + line[3:] + "</h2>")
        elif line.startswith("# "):
            out.append("<h1>" + line[2:] + "</h1>")
        elif line.startswith("- "):
            out.append("<li>" + line[2:] + "</li>")
        elif line.strip():
            out.append("<p>" + line + "</p>")
    return HTMLResponse("<!doctype html><html lang=ru><head><meta charset=utf-8><title>" + title +
                        " · ITKAM34</title><link rel=stylesheet href=/assets/theme.css></head>"
                        "<body style='padding:24px'><div class=legal-links><a href='/'>← На главную</a></div>"
                        "<div class=card>" + "".join(out) + "</div></body></html>")

@public_router.get("/dividends-how", response_class=HTMLResponse)
def dividends_how(request: Request, db: Session = Depends(get_db)):
    from app.core.settings_svc import get_setting as _gsdoc
    md = _gsdoc(db, "doc_dividends", "") or ""
    if not md:
        try:
            md = open("docs/dividends.md").read()
        except OSError:
            md = "Документ готовится."
    return _md_page146_text(md, "Как рассчитываются дивиденды")


@public_router.post("/invest/register")
def invest_register(request: Request, email: str = Form(), password: str = Form(),
                    invested: str = Form(""), db: Session = Depends(get_db)):
    import uuid as _uuid
    from app.services import dividends as dv
    from app.models import PartnerShare
    dv.ensure_tables()
    email = security.normalize_email(email)
    if "@" not in email or len(password) < 8:
        return RedirectResponse("/invest?error=3", status_code=303)
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        return RedirectResponse("/invest?error=4", status_code=303)
    price = int(_gs144(db, "invest_share_price_minor", "1000000") or 1000000)
    minor = parse_rub(invested)
    if minor < price:
        return RedirectResponse("/invest?error=5", status_code=303)
    share = max(1, minor // price)
    ip = request.client.host if request.client else ""
    user = User(email=email, password_hash=security.hash_password(password),
                referral_code=_uuid.uuid4().hex[:10], register_ip=ip or None,
                status="active")
    db.add(user)
    db.flush()
    ledger.get_wallet(db, user.id)
    db.add(PartnerShare(user_id=user.id, title=email, invested_minor=minor,
                        share_percent=share, status="pending"))
    db.commit()
    notify_admin(db, f"🧾 Новый инвестор: {email}, взнос {(minor/100):.0f} ₽, доля {share}% — станет активным после оплаты")
    return RedirectResponse("/invest?ok=1", status_code=303)
