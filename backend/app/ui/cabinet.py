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
from app.models import (
    LedgerEntry, PaymentRequest, Product, ServiceInstance, SupportTicket,
    TicketMessage, User, VpnAccount, VpnNode,
)
from app.services import ledger
from app.services.provisioning import enqueue_task

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
    if user is None or user.status != "active":  # заблокированного выкидываем сразу
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


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "lk/register.html", {"error": None})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(),
    password: str = Form(min_length=8),
    db: Session = Depends(get_db),
):
    email = security.normalize_email(email)
    if "@" not in email or len(email) > 254:
        return templates.TemplateResponse(
            request, "lk/register.html", {"error": "Укажите корректный email"}, status_code=400,
        )
    exists = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    taken = exists is not None
    if not taken:
        user = User(email=email, password_hash=security.hash_password(password))
        db.add(user)
        try:
            db.flush()
            ledger.get_wallet(db, user.id)
            db.commit()
        except IntegrityError:
            db.rollback()
            taken = True
    if taken:
        return templates.TemplateResponse(
            request, "lk/register.html",
            {"error": "Email уже зарегистрирован"}, status_code=409,
        )
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
        "user": user, "wallet": wallet, "entries": entries,
        "services": services, "payreqs": payreqs,
        "methods": TOPUP_METHODS, "notes": TOPUP_NOTES,
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
    if method not in dict(TOPUP_METHODS):
        method = "other"
    db.add(PaymentRequest(
        user_id=user.id, amount_minor=amount_minor, method=method,
        comment=comment.strip() or None, status="pending",
    ))
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
    link = sub_url = conf = None
    if account is not None:
        node = db.get(VpnNode, account.node_id)
        if node is not None and account.status != "deleted":
            cfg = get_adapter(node).render_config(db, account)
            link, sub_url, conf = cfg.get("link"), cfg.get("subscription_url"), cfg.get("config_text")
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
        "conf": conf, "qr_svg": qr_svg,
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
