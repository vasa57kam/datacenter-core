import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.db import get_db
from app.models import SupportTicket, TicketMessage, User
from app.services.node_import import import_node_from_inbound
from app.services.tariffs import UNITS, ensure_tariffs

router = APIRouter(prefix="/admin-ops", tags=["ops"])
templates = Jinja2Templates(directory="app/ui/templates")


def _guard(request: Request):
    if not request.session.get("admin_uid"):
        return RedirectResponse("/admin/login", status_code=303)
    return None


@router.get("/", response_class=HTMLResponse)
def ops_home(request: Request):
    r = _guard(request)
    return r or templates.TemplateResponse(request, "ops/home.html", {})


@router.get("/nodes/import", response_class=HTMLResponse)
def import_page(request: Request, error: str = "", ok: str = ""):
    r = _guard(request)
    return r or templates.TemplateResponse(request, "ops/import_node.html",
                                           {"error": error, "ok": ok, "inbound_json": ""})


@router.post("/nodes/import")
def import_submit(
    request: Request,
    inbound_json: str = Form(),
    inbound_id: int = Form(0),
    code: str = Form(""),
    name: str = Form(""),
    country: str = Form("NL"),
    endpoint_host: str = Form(""),
    api_url: str = Form(""),
    api_user: str = Form(""),
    api_key: str = Form(""),
    api_token: str = Form(""),
    db: Session = Depends(get_db),
):
    r = _guard(request)
    if r:
        return r
    try:
        node = import_node_from_inbound(
            db, inbound_json,
            inbound_id=inbound_id or None,
            code=code.strip() or None,
            name=name.strip() or None,
            country=country.strip() or "NL",
            endpoint_host=endpoint_host.strip() or None,
            api_url=api_url.strip() or None,
            api_user=api_user.strip() or None,
            api_key=api_key.strip() or None,
            api_token=api_token.strip() or None,
        )
        db.commit()
        return RedirectResponse(
            f"/admin-ops/nodes/import?ok=Нода+{node.code}+создана+inbound+{node.extra.get('inbound_id')}+порт+{node.endpoint_port}",
            status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(request, "ops/import_node.html",
                                          {"error": str(e), "ok": "", "inbound_json": inbound_json},
                                          status_code=400)


@router.get("/tariffs", response_class=HTMLResponse)
def tariffs_page(request: Request, error: str = "", ok: str = ""):
    r = _guard(request)
    return r or templates.TemplateResponse(request, "ops/tariffs.html",
                                           {"error": error, "ok": ok, "units": UNITS})


@router.post("/tariffs")
def tariffs_submit(
    request: Request,
    protocol: str = Form("vless"),
    country: str = Form("NL"),
    price_second: int = Form(2),
    price_minute: int = Form(150),
    price_gb: int = Form(100),
    price_month: int = Form(30000),
    db: Session = Depends(get_db),
):
    r = _guard(request)
    if r:
        return r
    try:
        res = ensure_tariffs(db, protocol.strip() or "vless", country.strip() or "NL",
                             {"second": price_second, "minute": price_minute,
                              "gb": price_gb, "month": price_month})
        db.commit()
        created = sum(1 for x in res if x["created"])
        return RedirectResponse(
            f"/admin-ops/tariffs?ok=Готово+создано+{created}+обновлено+{len(res) - created}",
            status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(request, "ops/tariffs.html",
                                          {"error": str(e), "ok": "", "units": UNITS}, status_code=400)


@router.get("/password", response_class=HTMLResponse)
def password_self_page(request: Request, error: str = "", ok: str = ""):
    r = _guard(request)
    return r or templates.TemplateResponse(request, "ops/password_self.html", {"error": error, "ok": ok})


@router.post("/password")
def password_self(
    request: Request,
    current: str = Form(),
    new: str = Form(min_length=8),
    confirm: str = Form(),
    db: Session = Depends(get_db),
):
    r = _guard(request)
    if r:
        return r
    user = db.get(User, int(request.session.get("admin_uid")))
    if user is None or not security.verify_password(current, user.password_hash):
        return templates.TemplateResponse(request, "ops/password_self.html",
                                          {"error": "Неверный текущий пароль", "ok": ""}, status_code=400)
    if new != confirm:
        return templates.TemplateResponse(request, "ops/password_self.html",
                                          {"error": "Пароли не совпадают", "ok": ""}, status_code=400)
    user.password_hash = security.hash_password(new)
    db.commit()
    return RedirectResponse("/admin-ops/password?ok=Пароль+изменён", status_code=303)


@router.get("/passwords", response_class=HTMLResponse)
def passwords_page(request: Request, error: str = "", ok: str = "", db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return templates.TemplateResponse(request, "ops/passwords.html",
                                      {"error": error, "ok": ok, "users": users})


@router.post("/passwords")
def passwords_set(
    request: Request,
    user_id: int = Form(),
    new: str = Form(min_length=8),
    db: Session = Depends(get_db),
):
    r = _guard(request)
    if r:
        return r
    user = db.get(User, user_id)
    if user is None:
        return RedirectResponse("/admin-ops/passwords?error=Пользователь+не+найден", status_code=303)
    user.password_hash = security.hash_password(new)
    db.commit()
    return RedirectResponse(f"/admin-ops/passwords?ok=Пароль+{user.email}+изменён", status_code=303)


@router.get("/tickets", response_class=HTMLResponse)
def ops_tickets(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    tickets = db.execute(select(SupportTicket).order_by(SupportTicket.id.desc())).scalars().all()
    return templates.TemplateResponse(request, "ops/tickets.html", {"tickets": tickets})


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ops_ticket_view(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        return RedirectResponse("/admin-ops/tickets", status_code=303)
    return templates.TemplateResponse(request, "ops/ticket_view.html", {"ticket": ticket})


@router.post("/tickets/{ticket_id}/reply")
def ops_ticket_reply(ticket_id: int, request: Request, body: str = Form(), db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is not None and body.strip():
        db.add(TicketMessage(ticket_id=ticket.id, author_role="manager", body=body.strip()))
        ticket.status = "answered"
        db.commit()
    return RedirectResponse(f"/admin-ops/tickets/{ticket_id}", status_code=303)


@router.post("/tickets/{ticket_id}/close")
def ops_ticket_close(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is not None:
        ticket.status = "closed"
        db.commit()
    return RedirectResponse(f"/admin-ops/tickets/{ticket_id}", status_code=303)


@router.get("/coupons", response_class=HTMLResponse)
def ops_coupons(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    from app.models import Coupon
    coupons = db.execute(select(Coupon).order_by(Coupon.id.desc()).limit(100)).scalars().all()
    return templates.TemplateResponse(request, "ops/coupons.html", {"coupons": coupons, "generated": None})


@router.post("/coupons/generate")
def ops_coupons_generate(
    request: Request,
    kind: str = Form(),
    amount: str = Form(),
    count: int = Form(1),
    prefix: str = Form(""),
    max_act: int = Form(1),
    days: int = Form(0),
    db: Session = Depends(get_db),
):
    r = _guard(request)
    if r:
        return r
    import secrets
    from datetime import timedelta
    from app.models import Coupon
    from app.core.tz import now as tz_now2

    kind = kind if kind in ("promo", "gift", "coupon") else "promo"
    try:
        amount_minor = int(round(float(amount.replace(",", ".")) * 100))
    except ValueError:
        amount_minor = 0
    if amount_minor <= 0:
        amount_minor = 10000
    count = max(1, min(count, 200))
    prefix = (prefix or {"promo": "PROMO", "gift": "GIFT", "coupon": "COUPON"}[kind]).upper().strip() or "CODE"
    expires = tz_now2() + timedelta(days=days) if days and days > 0 else None

    generated = []
    for _ in range(count):
        while True:
            code = f"{prefix}-{secrets.token_hex(3).upper()}"
            exists = db.execute(select(Coupon).where(Coupon.code == code)).scalar_one_or_none()
            if exists is None:
                break
        c = Coupon(code=code, kind=kind, amount_minor=amount_minor,
                   max_activations=max(1, max_act), expires_at=expires,
                   note=f"batch {count} шт")
        db.add(c)
        generated.append(code)
    db.commit()
    coupons = db.execute(select(Coupon).order_by(Coupon.id.desc()).limit(100)).scalars().all()
    return templates.TemplateResponse(request, "ops/coupons.html",
                                      {"coupons": coupons, "generated": generated})


@router.post("/coupons/{coupon_id}/toggle")
def ops_coupon_toggle(coupon_id: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r:
        return r
    from app.models import Coupon
    c = db.get(Coupon, coupon_id)
    if c is not None:
        c.active = not c.active
        db.commit()
    return RedirectResponse("/admin-ops/coupons", status_code=303)


# ================= Русская панель: разделы =================
from app.models import (
    LedgerEntry as _LedgerEntry, PaymentRequest as _PayReq, Product as _Product,
    ProvisioningTask as _Task, ServiceInstance as _Service, UsageSession as _Session,
    VpnAccount as _Account, VpnNode as _Node, Wallet as _Wallet,
)
from app.services import ledger as _ledger
from app.services.provisioning import enqueue_task as _enqueue


def _rub(m) -> str:
    return f"{(m or 0) / 100:.2f} ₽"


def _dt(v) -> str:
    return v.strftime("%d.%m.%y %H:%M") if v else "—"


@router.post("/users/{uid}/toggle")
def ops_user_toggle(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is not None and u.role != "admin":
        u.status = "blocked" if u.status == "active" else "active"
        _audit(db, request, "user_toggle", f"user={uid}")
        db.commit()
    return RedirectResponse("/admin-ops/users", status_code=303)


@router.get("/wallets", response_class=HTMLResponse)
def ops_wallets(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    wallets = db.execute(select(_Wallet).order_by(_Wallet.id)).scalars().all()
    rows = [{"cells": [w.id, w.user_id, _rub(w.balance_minor), _rub(w.promise_limit_minor)],
             "actions": [{"label": "Изменить", "url": f"/admin-ops/wallets/{w.id}", "method": "GET"}]}
            for w in wallets]
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Кошельки", "columns": ["№", "Пользователь", "Баланс", "Обещанный платёж"], "rows": rows})


@router.get("/wallets/{wid}", response_class=HTMLResponse)
def ops_wallet_edit(wid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    w = db.get(_Wallet, wid)
    if w is None: return RedirectResponse("/admin-ops/wallets", status_code=303)
    return templates.TemplateResponse(request, "ops/wallet_edit.html", {"w": w})


@router.post("/wallets/{wid}")
def ops_wallet_save(wid: int, request: Request, balance_rub: str = Form(), promise_rub: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    w = db.get(_Wallet, wid)
    if w is not None:
        try: w.balance_minor = int(round(float(balance_rub.replace(",", ".")) * 100))
        except ValueError: pass
        try: w.promise_limit_minor = max(0, int(round(float((promise_rub or "0").replace(",", ".")) * 100)))
        except ValueError: pass
        _audit(db, request, "wallet_edit", f"wallet={wid}")
        db.commit()
    return RedirectResponse("/admin-ops/wallets", status_code=303)


@router.get("/products", response_class=HTMLResponse)
def ops_products(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    products = db.execute(select(_Product).order_by(_Product.id)).scalars().all()
    rows = [{"cells": [p.id, p.name, p.unit, _rub(p.price_minor), "да" if p.active else "нет"],
             "actions": [
                 {"label": "Изменить", "url": f"/admin-ops/products/{p.id}", "method": "GET"},
                 {"label": "Выключить" if p.active else "Включить", "url": f"/admin-ops/products/{p.id}/toggle", "method": "POST", "cls": "sec"},
                 {"label": "Удалить", "url": f"/admin-ops/products/{p.id}/delete", "method": "POST", "cls": "danger", "confirm": "Удалить тариф? Доступно только если нет активных услуг."},
             ]} for p in products]
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Тарифы", "columns": ["№", "Название", "Единица", "Цена", "Виден"], "rows": rows,
        "extra": '<p><a class="btn" href="/admin-ops/products/new">+ Создать тариф</a></p>'})


@router.get("/products/{pid}", response_class=HTMLResponse)
def ops_product_edit(pid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    p = db.get(_Product, pid)
    if p is None: return RedirectResponse("/admin-ops/products", status_code=303)
    return templates.TemplateResponse(request, "ops/product_edit.html", {"p": p})


@router.post("/products/{pid}")
def ops_product_save(pid: int, request: Request, name: str = Form(), price_rub: str = Form(), unit: str = Form(), active: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    p = db.get(_Product, pid)
    if p is not None:
        p.name = name.strip() or p.name
        p.unit = unit if unit in ("minute", "second", "gb", "month", "one_time") else p.unit
        try: p.price_minor = int(round(float(price_rub.replace(",", ".")) * 100))
        except ValueError: pass
        p.active = bool(active)
        db.commit()
    return RedirectResponse("/admin-ops/products", status_code=303)


@router.post("/products/{pid}/toggle")
def ops_product_toggle(pid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    p = db.get(_Product, pid)
    if p is not None:
        p.active = not p.active
        db.commit()
    return RedirectResponse("/admin-ops/products", status_code=303)


@router.get("/services", response_class=HTMLResponse)
def ops_services(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    services = db.execute(select(_Service).order_by(_Service.id.desc())).scalars().all()
    rows = []
    for sv in services:
        acts = []
        if sv.status == "active":
            acts.append({"label": "Пауза", "url": f"/admin-ops/services/{sv.id}/suspend", "method": "POST", "cls": "warn"})
        elif sv.status == "suspended":
            acts.append({"label": "Возобновить", "url": f"/admin-ops/services/{sv.id}/resume", "method": "POST"})
        if sv.status in ("active", "suspended"):
            acts.append({"label": "Отключить", "url": f"/admin-ops/services/{sv.id}/terminate", "method": "POST", "cls": "danger", "confirm": "Отключить услугу и удалить аккаунт?"})
        rows.append({"cells": [sv.id, sv.user_id, sv.name, sv.status, _dt(sv.created_at)], "actions": acts})
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Услуги клиентов", "columns": ["№", "Клиент", "Название", "Состояние", "Создана"], "rows": rows})


@router.post("/services/{sid}/suspend")
def ops_service_suspend(sid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    sv = db.get(_Service, sid)
    if sv is not None and sv.status == "active":
        sv.status = "suspended"
        _enqueue(db, "service_instance", sv.id, "suspend")
        db.commit()
    return RedirectResponse("/admin-ops/services", status_code=303)


@router.post("/services/{sid}/resume")
def ops_service_resume(sid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    sv = db.get(_Service, sid)
    if sv is not None and sv.status == "suspended":
        sv.status = "active"
        _enqueue(db, "service_instance", sv.id, "resume")
        db.commit()
    return RedirectResponse("/admin-ops/services", status_code=303)


@router.post("/services/{sid}/terminate")
def ops_service_terminate(sid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    sv = db.get(_Service, sid)
    if sv is not None and sv.status in ("active", "suspended"):
        sv.status = "terminated"
        _enqueue(db, "service_instance", sv.id, "delete")
        db.commit()
    return RedirectResponse("/admin-ops/services", status_code=303)


@router.get("/nodes", response_class=HTMLResponse)
def ops_nodes(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    nodes = db.execute(select(_Node).order_by(_Node.id)).scalars().all()
    rows = [{"cells": [n.id, n.name, n.code, n.country, n.protocol, "да" if n.active else "нет"],
             "actions": [
                 {"label": "Изменить", "url": f"/admin-ops/nodes/{n.id}", "method": "GET"},
                 {"label": "Выключить" if n.active else "Включить", "url": f"/admin-ops/nodes/{n.id}/toggle", "method": "POST", "cls": "sec"},
             ]}
            for n in nodes]
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Ноды", "columns": ["№", "Название", "Код", "Страна", "Протокол", "Активна"], "rows": rows})


@router.post("/nodes/{nid}/toggle")
def ops_node_toggle(nid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    n = db.get(_Node, nid)
    if n is not None:
        n.active = not n.active
        db.commit()
    return RedirectResponse("/admin-ops/nodes", status_code=303)


@router.get("/accounts", response_class=HTMLResponse)
def ops_accounts(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    accounts = db.execute(select(_Account).order_by(_Account.id.desc())).scalars().all()
    rows = []
    for a in accounts:
        acts = []
        if a.status == "active":
            acts.append({"label": "Отключить", "url": f"/admin-ops/accounts/{a.id}/suspend", "method": "POST", "cls": "warn", "confirm": "Отключить аккаунт клиента?"})
        elif a.status == "suspended":
            acts.append({"label": "Включить", "url": f"/admin-ops/accounts/{a.id}/enable", "method": "POST"})
        rows.append({"cells": [a.id, a.service_instance_id, a.username, a.status, _dt(a.created_at)], "actions": acts})
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Аккаунты клиентов", "columns": ["№", "Услуга", "Логин клиента", "Статус", "Создан"], "rows": rows})


@router.get("/tasks", response_class=HTMLResponse)
def ops_tasks(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    tasks = db.execute(select(_Task).order_by(_Task.id.desc()).limit(200)).scalars().all()
    rows = []
    for t in tasks:
        acts = []
        if t.status in ("error", "pending"):
            acts.append({"label": "Повторить", "url": f"/admin-ops/tasks/{t.id}/retry", "method": "POST"})
            acts.append({"label": "Отменить", "url": f"/admin-ops/tasks/{t.id}/cancel", "method": "POST", "cls": "danger"})
        rows.append({"cells": [t.id, t.entity_type, t.entity_id, t.action, t.status, t.attempts, (t.error or "")[:60]], "actions": acts})
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Задачи выдачи", "columns": ["№", "Объект", "ID", "Действие", "Статус", "Попыток", "Ошибка"], "rows": rows})


@router.post("/tasks/{tid}/retry")
def ops_task_retry(tid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    t = db.get(_Task, tid)
    if t is not None:
        t.status = "pending"
        t.attempts = 0
        t.error = None
        db.commit()
    return RedirectResponse("/admin-ops/tasks", status_code=303)


@router.get("/payreqs", response_class=HTMLResponse)
def ops_payreqs(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    reqs = db.execute(select(_PayReq).order_by(_PayReq.id.desc())).scalars().all()
    rows = []
    for pr in reqs:
        acts = []
        if pr.status == "pending":
            acts.append({"label": "Одобрить и зачислить", "url": f"/admin-ops/payreqs/{pr.id}/approve", "method": "POST", "confirm": f"Зачислить {_rub(pr.amount_minor)}?"})
            acts.append({"label": "Отклонить", "url": f"/admin-ops/payreqs/{pr.id}/reject", "method": "POST", "cls": "danger"})
        rows.append({"cells": [pr.id, pr.user_id, _rub(pr.amount_minor), pr.method, pr.status, _dt(pr.created_at)], "actions": acts})
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Заявки на пополнение", "columns": ["№", "Клиент", "Сумма", "Способ", "Статус", "Когда"], "rows": rows})


@router.post("/payreqs/{pid}/approve")
def ops_payreq_approve(pid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    pr = db.get(_PayReq, pid)
    if pr is not None and pr.status == "pending":
        from app.services.payments import approve_payreq
        approve_payreq(db, pr, actor_email="админ")
        _audit(db, request, "payreq_approve", f"#{pid}")
        db.commit()
    return RedirectResponse("/admin-ops/payreqs", status_code=303)


@router.post("/payreqs/{pid}/reject")
def ops_payreq_reject(pid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    pr = db.get(_PayReq, pid)
    if pr is not None and pr.status == "pending":
        pr.status = "rejected"
        db.commit()
    return RedirectResponse("/admin-ops/payreqs", status_code=303)


# ================= Управление: создание и редактирование =================
from app.core import security as _security


@router.get("/users/new", response_class=HTMLResponse)
def ops_user_new_page(request: Request):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/user_edit.html", {"u": None})


@router.post("/users/new")
def ops_user_create(request: Request, email: str = Form(), role: str = Form("client"),
                    status: str = Form("active"), new_password: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    email = (email or "").strip().lower()
    if "@" not in email or len(new_password) < 8:
        return RedirectResponse("/admin-ops/users/new", status_code=303)
    exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if exists is None:
        db.add(User(email=email, role=role if role in ("client", "admin") else "client",
                    status=status if status in ("active", "blocked") else "active",
                    password_hash=_security.hash_password(new_password)))
        db.commit()
    else:
        pass  # Email already exists, silently redirect
    return RedirectResponse("/admin-ops/users", status_code=303)


@router.get("/users/{uid}", response_class=HTMLResponse)
def ops_user_edit(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is None: return RedirectResponse("/admin-ops/users", status_code=303)
    return templates.TemplateResponse(request, "ops/user_edit.html", {"u": u})


@router.post("/users/{uid}")
def ops_user_save(uid: int, request: Request, email: str = Form(), role: str = Form(),
                  status: str = Form(), new_password: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is not None:
        u.email = (email or u.email).strip().lower()
        u.role = role if role in ("client", "admin") else u.role
        u.status = status if status in ("active", "blocked") else u.status
        if new_password and len(new_password) >= 8:
            u.password_hash = _security.hash_password(new_password)
        db.commit()
    return RedirectResponse("/admin-ops/users", status_code=303)


@router.get("/nodes/{nid}", response_class=HTMLResponse)
def ops_node_edit(nid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    n = db.get(_Node, nid)
    if n is None: return RedirectResponse("/admin-ops/nodes", status_code=303)
    return templates.TemplateResponse(request, "ops/node_edit.html", {"n": n})


@router.post("/nodes/{nid}")
def ops_node_save(nid: int, request: Request, name: str = Form(), code: str = Form(),
                  country: str = Form(""), protocol: str = Form(), active: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    n = db.get(_Node, nid)
    if n is not None:
        n.name = name.strip() or n.name
        n.code = code.strip() or n.code
        n.country = country.strip() or n.country
        n.protocol = protocol.strip() or n.protocol
        n.active = bool(active)
        db.commit()
    return RedirectResponse("/admin-ops/nodes", status_code=303)


@router.post("/accounts/{aid}/suspend")
def ops_account_suspend(aid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    a = db.get(_Account, aid)
    if a is not None and a.status == "active":
        a.status = "suspended"
        if a.service_instance_id:
            _enqueue(db, "service_instance", a.service_instance_id, "suspend")
        db.commit()
    return RedirectResponse("/admin-ops/accounts", status_code=303)


@router.post("/accounts/{aid}/enable")
def ops_account_enable(aid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    a = db.get(_Account, aid)
    if a is not None and a.status == "suspended":
        a.status = "active"
        if a.service_instance_id:
            _enqueue(db, "service_instance", a.service_instance_id, "resume")
        db.commit()
    return RedirectResponse("/admin-ops/accounts", status_code=303)


@router.post("/sessions/{sid}/close")
def ops_session_close(sid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from app.core.tz import now as _now
    x = db.get(_Session, sid)
    if x is not None and x.status == "active":
        x.status = "closed"
        x.ended_at = _now()
        db.commit()
    return RedirectResponse("/admin-ops/sessions", status_code=303)


@router.post("/coupons/create")
def ops_coupon_create(request: Request, code: str = Form(), kind: str = Form("promo"),
                      amount: str = Form(), max_act: int = Form(1), days: int = Form(0),
                      note: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from datetime import timedelta
    from app.core.tz import now as _now
    from app.models import Coupon as _Coupon
    code = (code or "").strip().upper()
    if not code:
        return RedirectResponse("/admin-ops/coupons", status_code=303)
    try: amount_minor = int(round(float(amount.replace(",", ".")) * 100))
    except ValueError: amount_minor = 0
    if amount_minor <= 0:
        return RedirectResponse("/admin-ops/coupons", status_code=303)
    exists = db.execute(select(_Coupon).where(_Coupon.code == code)).scalar_one_or_none()
    if exists is None:
        db.add(_Coupon(code=code, kind=kind if kind in ("promo", "gift", "coupon") else "promo",
                       amount_minor=amount_minor, max_activations=max(1, max_act),
                       expires_at=_now() + timedelta(days=days) if days and days > 0 else None,
                       note=note.strip() or None))
        db.commit()
    return RedirectResponse("/admin-ops/coupons", status_code=303)


@router.post("/coupons/{cid}/delete")
def ops_coupon_delete(cid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from app.models import Coupon as _Coupon
    c = db.get(_Coupon, cid)
    if c is not None:
        db.delete(c)
        db.commit()
    return RedirectResponse("/admin-ops/coupons", status_code=303)


@router.get("/products/new", response_class=HTMLResponse)
def ops_product_new_page(request: Request):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/product_new.html", {})


@router.post("/products/new")
def ops_product_create(request: Request, code: str = Form(), name: str = Form(),
                       service_type: str = Form("vpn"), unit: str = Form("minute"),
                       price_rub: str = Form(), active: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    code = (code or "").strip()
    if not code:
        return RedirectResponse("/admin-ops/products/new", status_code=303)
    try: price_minor = int(round(float(price_rub.replace(",", ".")) * 100))
    except ValueError: price_minor = 0
    exists = db.execute(select(_Product).where(_Product.code == code)).scalar_one_or_none()
    if exists is None:
        db.add(_Product(code=code, name=name.strip() or code,
                        service_type=service_type if service_type in ("vpn", "cctv", "vps") else "vpn",
                        unit=unit if unit in ("minute", "second", "gb", "month", "one_time") else "minute",
                        price_minor=price_minor, active=bool(active),
                        config={"protocol": "vless"} if service_type == "vpn" else {}))
        db.commit()
    else:
        pass  # Code already exists, silently redirect
    return RedirectResponse("/admin-ops/products", status_code=303)


# ================= Поиск, пагинация, очистка =================
def _paginate(total: int, page: int, per_page: int = 50) -> dict:
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    return {
        "current": page, "pages": pages, "per_page": per_page,
        "prev": page - 1 if page > 1 else None,
        "next": page + 1 if page < pages else None,
    }


@router.get("/ledger", response_class=HTMLResponse)
def ops_ledger(request: Request, page: int = 1, user_id: str = "", reason: str = "", db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    q = select(_LedgerEntry)
    if user_id.isdigit():
        q = q.where(_LedgerEntry.wallet_id == int(user_id))
    if reason.strip():
        q = q.where(_LedgerEntry.reason.ilike(f"%{reason.strip()}%"))
    total = db.execute(select(func.count(_LedgerEntry.id))).scalar() or 0
    p = _paginate(total, page, 50)
    entries = db.execute(q.order_by(_LedgerEntry.id.desc()).offset((p["current"] - 1) * p["per_page"]).limit(p["per_page"])).scalars().all()
    rows = [{"cells": [e.id, e.wallet_id, e.entry_type, _rub(e.amount_minor), e.reason, _dt(e.created_at)], "actions": []} for e in entries]
    query = "&".join(f"{k}={v}" for k, v in [("user_id", user_id), ("reason", reason)] if v)
    p["query"] = query
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Финансовый журнал", "columns": ["№", "Кошелёк", "Тип", "Сумма", "Назначение", "Когда"], "rows": rows,
        "total": total, "pagination": p, "search_form": {"user_id": user_id, "reason": reason},
        "extra": f'<p><form method="post" action="/admin-ops/ledger/cleanup" style="display:inline" onsubmit="return confirm(\'Удалить записи старше 90 дней?\')"><button class="btn warn" type="submit">Очистить старше 90 дней</button></form></p>'
    })


@router.post("/ledger/cleanup")
def ops_ledger_cleanup(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from datetime import timedelta
    from app.core.tz import now as _now
    cutoff = _now() - timedelta(days=90)
    db.execute(select(_LedgerEntry).where(_LedgerEntry.created_at < cutoff))
    old = db.execute(select(_LedgerEntry).where(_LedgerEntry.created_at < cutoff)).scalars().all()
    for e in old:
        db.delete(e)
    db.commit()
    return RedirectResponse("/admin-ops/ledger", status_code=303)


@router.get("/sessions", response_class=HTMLResponse)
def ops_sessions(request: Request, page: int = 1, status: str = "", service_id: str = "", db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    q = select(_Session)
    if status.strip():
        q = q.where(_Session.status == status.strip())
    if service_id.isdigit():
        q = q.where(_Session.service_instance_id == int(service_id))
    total = db.execute(select(func.count(_Session.id))).scalar() or 0
    p = _paginate(total, page, 50)
    sessions = db.execute(q.order_by(_Session.id.desc()).offset((p["current"] - 1) * p["per_page"]).limit(p["per_page"])).scalars().all()
    rows = []
    for x in sessions:
        acts = []
        if x.status == "active":
            acts.append({"label": "Закрыть", "url": f"/admin-ops/sessions/{x.id}/close", "method": "POST", "cls": "warn"})
        rows.append({"cells": [x.id, x.service_instance_id, x.status, _dt(x.started_at), _dt(x.ended_at), _rub(x.cost_minor)], "actions": acts})
    query = "&".join(f"{k}={v}" for k, v in [("status", status), ("service_id", service_id)] if v)
    p["query"] = query
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Сессии использования", "columns": ["№", "Услуга", "Статус", "Начало", "Конец", "Стоимость"], "rows": rows,
        "total": total, "pagination": p, "search_form": {"status": status, "service_id": service_id},
        "extra": f'<p><form method="post" action="/admin-ops/sessions/cleanup" style="display:inline" onsubmit="return confirm(\'Удалить закрытые сессии старше 30 дней?\')"><button class="btn warn" type="submit">Очистить закрытые старше 30 дней</button></form></p>'
    })


@router.post("/sessions/cleanup")
def ops_sessions_cleanup(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from datetime import timedelta
    from app.core.tz import now as _now
    cutoff = _now() - timedelta(days=30)
    old = db.execute(select(_Session).where(_Session.status == "closed", _Session.ended_at < cutoff)).scalars().all()
    for x in old:
        db.delete(x)
    db.commit()
    return RedirectResponse("/admin-ops/sessions", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def ops_users(request: Request, page: int = 1, email: str = "", status: str = "", db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    q = select(User)
    if email.strip():
        q = q.where(User.email.ilike(f"%{email.strip()}%"))
    if status.strip():
        q = q.where(User.status == status.strip())
    total = db.execute(select(func.count(User.id))).scalar() or 0
    p = _paginate(total, page, 50)
    users = db.execute(q.order_by(User.id).offset((p["current"] - 1) * p["per_page"]).limit(p["per_page"])).scalars().all()
    rows = []
    for u in users:
        acts = []
        if u.role != "admin":
            acts.append({"label": "Заблокировать" if u.status == "active" else "Разблокировать",
                         "url": f"/admin-ops/users/{u.id}/toggle", "method": "POST",
                         "cls": "warn" if u.status == "active" else ""})
        acts.append({"label": "Изменить", "url": f"/admin-ops/users/{u.id}", "method": "GET"})
        rows.append({"cells": [u.id, u.email, u.role, u.status, _dt(u.created_at)], "actions": acts})
    query = "&".join(f"{k}={v}" for k, v in [("email", email), ("status", status)] if v)
    p["query"] = query
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Пользователи", "columns": ["№", "Email", "Роль", "Статус", "Создан"], "rows": rows,
        "total": total, "pagination": p, "search_form": {"email": email, "status": status},
        "extra": '<p><a class="btn" href="/admin-ops/users/new">+ Создать пользователя</a></p>'
    })


@router.post("/products/{pid}/delete")
def ops_product_delete(pid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    p = db.get(_Product, pid)
    if p is not None:
        active_services = db.execute(select(func.count(_Service.id)).where(_Service.product_id == pid, _Service.status.in_(("active", "suspended")))).scalar() or 0
        if active_services > 0:
            return RedirectResponse("/admin-ops/products", status_code=303)
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin-ops/products", status_code=303)


# ================= v81: уведомления, аудит, статистика, bulk, CSV =================
from app.models import AuditLog as _Audit, Notification as _Notif


def _audit(db, request, action: str, target: str = "") -> None:
    uid = request.session.get("admin_uid") or request.session.get("uid")
    email = ""
    if uid:
        u = db.get(User, int(uid))
        email = u.email if u is not None else ""
    db.add(_Audit(actor_id=uid, actor_email=email, action=action, target=target))


@router.get("/notifications", response_class=HTMLResponse)
def ops_notifications(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    items = db.execute(select(_Notif).order_by(_Notif.id.desc()).limit(200)).scalars().all()
    return templates.TemplateResponse(request, "ops/notifications.html", {"items": items})


@router.get("/notifications/count.json")
def ops_notifications_count(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return {"unread": 0}
    n = db.execute(select(func.count(_Notif.id)).where(_Notif.read_at.is_(None))).scalar() or 0
    return {"unread": n}


@router.post("/notifications/{nid}/read")
def ops_notification_read(nid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from app.core.tz import now as _now
    n = db.get(_Notif, nid)
    if n is not None:
        n.read_at = _now()
        db.commit()
    return RedirectResponse("/admin-ops/notifications", status_code=303)


@router.post("/notifications/read_all")
def ops_notifications_read_all(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from app.core.tz import now as _now
    unread = db.execute(select(_Notif).where(_Notif.read_at.is_(None))).scalars().all()
    for n in unread:
        n.read_at = _now()
    db.commit()
    return RedirectResponse("/admin-ops/notifications", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
def ops_audit(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    items = db.execute(select(_Audit).order_by(_Audit.id.desc()).limit(300)).scalars().all()
    return templates.TemplateResponse(request, "ops/audit.html", {"items": items})


@router.get("/stats", response_class=HTMLResponse)
def ops_stats(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from datetime import timedelta
    from app.core.tz import now as _now
    days = []
    total = 0
    for i in range(13, -1, -1):
        d0 = (_now() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = d0 + timedelta(days=1)
        summ = db.execute(
            select(func.coalesce(func.sum(_LedgerEntry.amount_minor), 0)).where(
                _LedgerEntry.entry_type == "debit",
                _LedgerEntry.created_at >= d0, _LedgerEntry.created_at < d1)
        ).scalar() or 0
        rub = round(abs(summ) / 100, 2)
        total += rub
        days.append({"label": d0.strftime("%d.%m"), "rub": rub, "raw": rub})
    mx = max([d["raw"] for d in days] + [1])
    for d in days:
        d["h"] = int(4 + 150 * d["raw"] / mx)
    kpi = {
        "clients": db.execute(select(func.count(User.id)).where(User.role == "client")).scalar() or 0,
        "active_services": db.execute(select(func.count(_Service.id)).where(_Service.status == "active")).scalar() or 0,
        "revenue_total": round(total, 2),
        "pending": db.execute(select(func.count(_PayReq.id)).where(_PayReq.status == "pending")).scalar() or 0,
    }
    return templates.TemplateResponse(request, "ops/stats.html", {"chart": days, "kpi": kpi})


@router.get("/ledger/export.csv")
def ops_ledger_export(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from fastapi.responses import StreamingResponse
    import csv, io
    entries = db.execute(select(_LedgerEntry).order_by(_LedgerEntry.id.desc()).limit(10000)).scalars().all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Wallet", "Type", "Amount RUB", "Reason", "Created"])
    for e in entries:
        w.writerow([e.id, e.wallet_id, e.entry_type, f"{e.amount_minor/100:.2f}", e.reason, e.created_at.isoformat()])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ledger.csv"})


@router.post("/users/bulk_block")
def ops_users_bulk_block(request: Request, email: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    q = select(User).where(User.role == "client")
    if email.strip():
        q = q.where(User.email.ilike(f"%{email.strip()}%"))
    users = db.execute(q).scalars().all()
    for u in users:
        u.status = "blocked"
    _audit(db, request, "bulk_block", f"filter={email!r} count={len(users)}")
    db.commit()
    return RedirectResponse("/admin-ops/users", status_code=303)


@router.post("/users/{uid}/suspend_all")
def ops_user_suspend_all(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    services = db.execute(select(_Service).where(_Service.user_id == uid, _Service.status == "active")).scalars().all()
    for sv in services:
        sv.status = "suspended"
        _enqueue(db, "service_instance", sv.id, "suspend")
    _audit(db, request, "suspend_all", f"user={uid} count={len(services)}")
    db.commit()
    return RedirectResponse("/admin-ops/services", status_code=303)
