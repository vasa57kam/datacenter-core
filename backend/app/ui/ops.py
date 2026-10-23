import json
import subprocess

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
    import time as _t
    exp = request.session.get("exp")
    if exp and _t.time() > int(exp):
        request.session.clear()
    role = request.session.get("staff_role")
    if role == "admin" or request.session.get("admin_uid"):
        return None
    if role == "cashier":
        return RedirectResponse("/lk/kassa", status_code=303)
    return RedirectResponse("/admin-ops/staff-login", status_code=303)


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
from app.models import PaymentMethod as _PM, SystemSetting as _SS
from app.services import ledger as _ledger
from app.services.provisioning import enqueue_task as _enqueue


def _gset(db, key: str, default: str = "") -> str:
    from app.core.settings_svc import get_setting
    return get_setting(db, key, default)


def _sset(db, key: str, value: str) -> None:
    from app.core.settings_svc import set_setting
    set_setting(db, key, value)


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
def ops_user_new_page(request: Request, error: str = ""):
    r = _guard(request)
    if r: return r
    errs = {"3": "Пароль короче 8 символов", "4": "Некорректный email"}
    return templates.TemplateResponse(request, "ops/user_edit.html", {"u": None, "error": errs.get(error, "")})


@router.post("/users/new")
def ops_user_create(request: Request, email: str = Form(), role: str = Form("client"),
                    status: str = Form("active"), new_password: str = Form(""), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    email = (email or "").strip().lower()
    if "@" not in email:
        return RedirectResponse("/admin-ops/users/new?error=4", status_code=303)
    if len(new_password or "") < 8:
        return RedirectResponse("/admin-ops/users/new?error=3", status_code=303)
    exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if exists is not None:
        return RedirectResponse("/admin-ops/users?error=2", status_code=303)
    try:
        u = User(email=email, role=role if role in ("client", "admin", "cashier") else "client",
                 status=status if status in ("active", "blocked") else "active",
                 password_hash=_security.hash_password(new_password))
        db.add(u)
        db.flush()
        _ledger.get_wallet(db, u.id)
        _audit(db, request, "user_create", email)
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse("/admin-ops/users?error=1", status_code=303)
    return RedirectResponse("/admin-ops/users?ok=1", status_code=303)


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
        u.role = role if role in ("client", "admin", "cashier") else u.role
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
        if u.role != "admin":
            acts.append({"label": "Удалить", "url": f"/admin-ops/users/{u.id}/delete", "method": "POST", "cls": "danger", "confirm": "Удалить пользователя со всеми услугами и кошельком? Безвозвратно."})
        rows.append({"cells": [u.id, u.email, u.role, {"active": "активен", "blocked": "заблокирован", "pending_verify": "на проверке"}.get(u.status, u.status), _dt(u.created_at)], "actions": acts})
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
from app.models import AuditLog as _Audit, Notification as _Notif, PatchHistory as _PH


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
    from app.core.tz import as_msk, now as _now
    chart, kpi = [], {"clients": 0, "active_services": 0, "revenue_total": 0, "pending": 0}
    try:
        now = _now()
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=13)
        entries = db.execute(
            select(_LedgerEntry).where(_LedgerEntry.entry_type == "debit", _LedgerEntry.created_at >= day0)
            .order_by(_LedgerEntry.id.desc()).limit(20000)
        ).scalars().all()
        sums = {}
        for e in entries:
            d = as_msk(e.created_at).replace(hour=0, minute=0, second=0, microsecond=0)
            sums[d] = sums.get(d, 0) + abs(e.amount_minor or 0)
        total = 0.0
        for i in range(14):
            d = day0 + timedelta(days=i)
            rub = round(sums.get(d, 0) / 100, 2)
            total += rub
            chart.append({"label": d.strftime("%d.%m"), "rub": rub, "raw": rub})
        mx = max([c["raw"] for c in chart] + [1])
        for c in chart:
            c["h"] = int(4 + 150 * c["raw"] / mx)
        kpi = {
            "clients": db.execute(select(func.count(User.id)).where(User.role == "client")).scalar() or 0,
            "active_services": db.execute(select(func.count(_Service.id)).where(_Service.status == "active")).scalar() or 0,
            "revenue_total": round(total, 2),
            "pending": db.execute(select(func.count(_PayReq.id)).where(_PayReq.status == "pending")).scalar() or 0,
        }
    except Exception as exc:
        kpi["note"] = f"частичные данные: {exc}"
    try:
        return templates.TemplateResponse(request, "ops/stats.html", {"chart": chart, "kpi": kpi})
    except Exception:
        import traceback
        return HTMLResponse("<h3>Диагностика stats</h3><pre style='white-space:pre-wrap'>"
                            + traceback.format_exc() + "</pre>")



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


# ================= Служебный вход (админ / кассир) =================

@router.get("/staff-login", response_class=HTMLResponse)
def staff_login_page(request: Request):
    role = request.session.get("staff_role")
    if role == "admin" or request.session.get("admin_uid"):
        return RedirectResponse("/admin-ops/", status_code=303)
    if role == "cashier":
        return RedirectResponse("/lk/kassa", status_code=303)
    return templates.TemplateResponse(request, "ops/login.html", {"error": None})


@router.post("/staff-login")
def staff_login(request: Request, email: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    import time as _time
    from app.core import security as _sec
    u = db.execute(
        select(User).where(User.email == (email or "").strip().lower(), User.status == "active")
    ).scalar_one_or_none()
    if u is None or u.role not in ("admin", "cashier") or not _sec.verify_password(password or "", u.password_hash):
        return templates.TemplateResponse(request, "ops/login.html",
                                          {"error": "Неверные данные или нет служебного доступа"}, status_code=401)
    request.session["uid"] = u.id
    request.session["staff_role"] = u.role
    if u.role == "admin":
        request.session["admin_uid"] = u.id
    request.session["exp"] = int(_time.time()) + 12 * 3600
    return RedirectResponse("/admin-ops/" if u.role == "admin" else "/lk/kassa", status_code=303)


@router.post("/staff-logout")
def staff_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin-ops/staff-login", status_code=303)


# ================= v99: верификация, удаление, регламент =================
@router.get("/verify", response_class=HTMLResponse)
def ops_verify(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    users = db.execute(select(User).where(User.status == "pending_verify").order_by(User.id)).scalars().all()
    rows = []
    for u in users:
        rows.append({"cells": [u.id, u.email, u.phone or "—", u.register_ip or "—", _dt(u.created_at)],
                     "actions": [
                         {"label": "Доверить и активировать", "url": f"/admin-ops/verify/{u.id}/ok", "method": "POST"},
                         {"label": "Заблокировать", "url": f"/admin-ops/verify/{u.id}/block", "method": "POST", "cls": "danger"},
                     ]})
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "🕵 Верификация: ожидают подтверждения", "columns": ["№", "Email", "Телефон", "IP", "Регистрация"],
        "rows": rows, "note": "Позвони или напиши клиенту, убедись, что человек реальный, и нажми «Доверить»."})


@router.post("/verify/{uid}/ok")
def ops_verify_ok(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is not None and u.status == "pending_verify":
        u.status = "active"
        _audit(db, request, "verify_ok", u.email)
        from app.core.notifications import notify_admin
        notify_admin(db, f"✅ Аккаунт {u.email} верифицирован и активирован")
        db.commit()
    return RedirectResponse("/admin-ops/verify", status_code=303)


@router.post("/verify/{uid}/block")
def ops_verify_block(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is not None and u.status == "pending_verify":
        u.status = "blocked"
        _audit(db, request, "verify_block", u.email)
        db.commit()
    return RedirectResponse("/admin-ops/verify", status_code=303)


@router.post("/users/{uid}/delete")
def ops_user_delete(uid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    u = db.get(User, uid)
    if u is None or u.role == "admin":
        return RedirectResponse("/admin-ops/users", status_code=303)
    try:
        services = db.execute(select(_Service).where(_Service.user_id == uid)).scalars().all()
        for sv in services:
            if sv.status in ("active", "suspended"):
                sv.status = "terminated"
                _enqueue(db, "service_instance", sv.id, "delete")
        db.flush()
        for sv in services:
            for a in db.execute(select(_Account).where(_Account.service_instance_id == sv.id)).scalars().all():
                db.delete(a)
            for x in db.execute(select(_Session).where(_Session.service_instance_id == sv.id)).scalars().all():
                db.delete(x)
            db.delete(sv)
        wallet = db.execute(select(_Wallet).where(_Wallet.user_id == uid)).scalar_one_or_none()
        if wallet is not None:
            for e in db.execute(select(_LedgerEntry).where(_LedgerEntry.wallet_id == wallet.id)).scalars().all():
                db.delete(e)
            db.delete(wallet)
        for pr in db.execute(select(_PayReq).where(_PayReq.user_id == uid)).scalars().all():
            db.delete(pr)
        db.delete(u)
        _audit(db, request, "user_delete", f"user={uid}")
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse("/admin-ops/users?error=9", status_code=303)
    return RedirectResponse("/admin-ops/users?ok=2", status_code=303)


@router.get("/rules", response_class=HTMLResponse)
def ops_rules(request: Request):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/rules.html", {})


@router.get("/settings", response_class=HTMLResponse)
def ops_settings(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/settings.html", {
        "auto_enabled": _gset(db, "auto_approve_enabled", "1") == "1",
        "auto_limit": round(int(_gset(db, "auto_approve_limit_minor", "50000")) / 100, 2),
        "offline_mode": _gset(db, "offline_mode", "1") == "1",
        "cap_hours": _gset(db, "offline_cap_hours", "72"),
    })


@router.post("/settings")
def ops_settings_save(request: Request, auto_enabled: str = Form(""), auto_limit_rub: str = Form(""),
                      offline_mode: str = Form(""), cap_hours: int = Form(72), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    _sset(db, "auto_approve_enabled", "1" if auto_enabled else "0")
    try:
        _sset(db, "auto_approve_limit_minor", str(int(round(float(auto_limit_rub.replace(",", ".")) * 100))))
    except ValueError:
        pass
    _sset(db, "offline_mode", "1" if offline_mode else "0")
    _sset(db, "offline_cap_hours", str(max(1, min(cap_hours, 720))))
    _audit(db, request, "settings_save", "auto+offline")
    db.commit()
    return RedirectResponse("/admin-ops/settings", status_code=303)


def _seed_methods(db) -> None:
    cnt = db.execute(select(func.count(_PM.id))).scalar() or 0
    if cnt:
        return
    for code, title, instr, visible, order in [
        ("transfer", "Перевод на карту", "Переведите сумму на карту Сбербанк по номеру +7 000 000-00-00 (Имя Фамилия). В комментарии укажите ваш email.", True, 10),
        ("cash", "Наличные", "Передайте наличные администратору или кассиру.", False, 20),
        ("other", "Другое", "Опишите в комментарии способ оплаты — администратор свяжется с вами.", True, 30)]:
        db.add(_PM(code=code, title=title, instructions=instr, client_visible=visible, sort_order=order))
    db.commit()


@router.get("/paymethods", response_class=HTMLResponse)
def ops_paymethods(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    _seed_methods(db)
    items = db.execute(select(_PM).order_by(_PM.sort_order)).scalars().all()
    rows = [{"cells": [m.id, m.code, m.title, "да" if m.client_visible else "нет (касса)", "да" if m.active else "нет"],
             "actions": [{"label": "Изменить", "url": f"/admin-ops/paymethods/{m.id}", "method": "GET"},
                         {"label": "Выключить" if m.active else "Включить", "url": f"/admin-ops/paymethods/{m.id}/toggle", "method": "POST", "cls": "sec"}]}
            for m in items]
    return templates.TemplateResponse(request, "ops/table.html", {
        "title": "Способы оплаты", "columns": ["№", "Код", "Название", "Виден клиенту", "Активен"], "rows": rows,
        "extra": '<p><a class="btn" href="/admin-ops/paymethods/new">+ Создать способ</a></p>'})


@router.get("/paymethods/new", response_class=HTMLResponse)
def ops_paymethod_new(request: Request):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/paymethod_edit.html", {"m": None})


@router.post("/paymethods/new")
def ops_paymethod_create(request: Request, code: str = Form(), title: str = Form(), instructions: str = Form(""),
                         client_visible: str = Form(""), sort_order: int = Form(0), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    code = (code or "").strip().lower()
    if code and db.execute(select(_PM).where(_PM.code == code)).scalar_one_or_none() is None:
        db.add(_PM(code=code, title=title.strip() or code, instructions=instructions,
                   client_visible=bool(client_visible), sort_order=sort_order))
        db.commit()
    return RedirectResponse("/admin-ops/paymethods", status_code=303)


@router.get("/paymethods/{mid}", response_class=HTMLResponse)
def ops_paymethod_edit(mid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    m = db.get(_PM, mid)
    if m is None: return RedirectResponse("/admin-ops/paymethods", status_code=303)
    return templates.TemplateResponse(request, "ops/paymethod_edit.html", {"m": m})


@router.post("/paymethods/{mid}")
def ops_paymethod_save(mid: int, request: Request, title: str = Form(), instructions: str = Form(""),
                       client_visible: str = Form(""), sort_order: int = Form(0), db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    m = db.get(_PM, mid)
    if m is not None:
        m.title = title.strip() or m.title
        m.instructions = instructions
        m.client_visible = bool(client_visible)
        m.sort_order = sort_order
        _audit(db, request, "paymethod_edit", m.code)
        db.commit()
    return RedirectResponse("/admin-ops/paymethods", status_code=303)


@router.post("/paymethods/{mid}/toggle")
def ops_paymethod_toggle(mid: int, request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    m = db.get(_PM, mid)
    if m is not None:
        m.active = not m.active
        db.commit()
    return RedirectResponse("/admin-ops/paymethods", status_code=303)


@router.get("/cashier-guide", response_class=HTMLResponse)
def ops_cashier_guide(request: Request):
    r = _guard(request)
    if r: return r
    return templates.TemplateResponse(request, "ops/cashier_guide.html", {})


@router.get("/status", response_class=HTMLResponse)
def ops_status(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    import os as _os
    db_ver = db.get(_SS, "app_version")
    db_commit = db.get(_SS, "app_commit")
    deployed = _os.environ.get("DEPLOYED_COMMIT", "—")
    origin = _os.environ.get("ORIGIN_COMMIT", "—")
    repo_version = "—"
    try:
        with open("/app/VERSION") as f:
            repo_version = f.read().strip()
    except Exception:
        pass
    commits = []
    try:
        out = subprocess.check_output(
            ["git", "-C", "/app", "log", "--oneline", "-8", "--format=%ad|%h|%s"],
            stderr=subprocess.STDOUT, timeout=10).decode("utf-8", errors="replace")
        for line in out.strip().split("\n")[:8]:
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"date": parts[0], "hash": parts[1], "msg": parts[2]})
    except Exception:
        pass
    history = db.execute(select(_PH).order_by(_PH.id.desc()).limit(50)).scalars().all()
    sync_ok = (origin == "—") or (deployed == origin)
    return templates.TemplateResponse(request, "ops/status.html", {
        "db_version": db_ver.value if db_ver else "—", "repo_version": repo_version,
        "deployed": deployed[:8] if deployed != "—" else deployed,
        "origin": origin[:8] if origin != "—" else origin,
        "db_commit": db_commit.value[:8] if db_commit else "—",
        "sync_ok": sync_ok, "commits": commits, "history": history,
        "patches_applied": len(history)})


@router.post("/guard/run")
def ops_guard_run(request: Request, db: Session = Depends(get_db)):
    r = _guard(request)
    if r: return r
    from app.services.offline_guard import run_guard
    run_guard(db=db)
    _audit(db, request, "guard_run", "manual")
    db.commit()
    return RedirectResponse("/admin-ops/settings", status_code=303)


# ================= v138: Промо-центр и очистка журнала (admin-ops) =================
for _n138, _imp138 in (
    ("HTMLResponse", "from fastapi.responses import HTMLResponse"),
    ("RedirectResponse", "from fastapi.responses import RedirectResponse"),
    ("Form", "from fastapi import Form"),
    ("HTTPException", "from fastapi import HTTPException"),
    ("Depends", "from fastapi import Depends"),
    ("Session", "from sqlalchemy.orm import Session"),
    ("Request", "from fastapi import Request"),
):
    try:
        eval(_n138)
    except NameError:
        exec(_imp138)
try:
    get_db
except NameError:
    from app.db import get_db

from fastapi.templating import Jinja2Templates as _JT138
_t138 = Jinja2Templates(directory="app/ui/templates")

def _admin138(db, request):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return u

_PROMO138 = [
    ("cashback_percent", "Кэшбэк с пополнения, % (0 — выключен)", "3"),
    ("cashback_min_minor", "Порог кэшбэка, копеек (100000 = 1000 ₽)", "100000"),
    ("referral_reward_minor", "Награда за реферала, копеек (0 — выключена)", "5000"),
    ("auto_approve_enabled", "Доверительный лимит: включён (1/0)", "1"),
    ("auto_approve_limit_minor", "Доверительный лимит, копеек", "50000"),
    ("auto_approve_max_uses", "Доверительный лимит: использований на кошелёк", "1"),    ("invest_share_price_minor", "Цена 1% доли пула для инвесторов, копеек", "1000000"),

]

def _cnt138(db, d, kind):
    from app.models import LedgerEntry as _LE
    from sqlalchemy import func as _fn, select as _sel
    from app.core.tz import now as _now138
    from datetime import timedelta as _td
    cutoff = _now138() - _td(days=d)
    w = [_LE.created_at < cutoff]
    if kind == "usage":
        w.append(_LE.reason.like("vpn_usage_%"))
    elif kind == "debits":
        w.append(_LE.amount_minor < 0)
    return db.execute(_sel(_fn.count()).select_from(_LE).where(*w)).scalar() or 0

@router.get("/promo", response_class=HTMLResponse)
def promo_ops138(request: Request, ok: str = "", msg: str = "",
                 days: str = "90", kind: str = "usage",
                 db: Session = Depends(get_db)):
    user = _admin138(db, request)
    from app.core.settings_svc import get_setting as _gs
    d = max(1, int(days or 90))
    vals = {k: (_gs(db, k, dd) or dd) for k, _, dd in _PROMO138}
    return _t138.TemplateResponse(request, "ops_promo.html", {
        "user": user, "keys": _PROMO138, "vals": vals, "ok": ok,
        "msg": msg, "days": d, "kind": kind, "cnt": _cnt138(db, d, kind)})

@router.post("/promo")
async def promo_ops138_save(request: Request, db: Session = Depends(get_db)):
    _admin138(db, request)
    form = await request.form()
    from app.core.settings_svc import set_setting as _ss
    for key, _, dd in _PROMO138:
        v = (form.get(key) or "").strip() or dd
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
            v = dd
        _ss(db, key, v)
    db.commit()
    return RedirectResponse("/admin-ops/promo?ok=1", status_code=303)

@router.post("/ledger/clean")
def ledger_clean138(request: Request, days: str = Form("90"),
                    kind: str = Form("usage"), confirm: str = Form(""),
                    db: Session = Depends(get_db)):
    _admin138(db, request)
    if confirm.strip() != "УДАЛИТЬ":
        return RedirectResponse("/admin-ops/promo?msg=no-confirm", status_code=303)
    if kind not in ("usage", "debits"):
        return RedirectResponse("/admin-ops/promo?msg=bad-kind", status_code=303)
    from app.models import LedgerEntry as _LE
    from sqlalchemy import delete as _del, select as _sel
    from app.core.tz import now as _now138
    from datetime import timedelta as _td
    d = max(1, int(days or 90))
    cutoff = _now138() - _td(days=d)
    w = [_LE.created_at < cutoff]
    if kind == "usage":
        w.append(_LE.reason.like("vpn_usage_%"))
    else:
        w.append(_LE.amount_minor < 0)
    ids = [r[0] for r in db.execute(
        _sel(_LE.id).where(*w).order_by(_LE.id.asc()).limit(200000)).all()]
    done = 0
    for i in range(0, len(ids), 2000):
        done += db.execute(_del(_LE).where(_LE.id.in_(ids[i:i+2000]))).rowcount
    db.commit()
    return RedirectResponse(f"/admin-ops/promo?msg=deleted-{done}", status_code=303)

from app.core.labels import finalize_human as _fh141
templates.env.finalize = _fh141
_t138.env.finalize = _fh141


# ================= v143: Дивиденды (admin-ops) =================
@router.get("/dividends", response_class=HTMLResponse)
def dividends_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.services import dividends as dv
    dv.ensure_tables()
    from app.core.settings_svc import get_setting as _gs
    partners = db.execute(select(dv.PartnerShare).order_by(dv.PartnerShare.id)).scalars().all()
    accruals = db.execute(select(dv.DividendAccrual).order_by(dv.DividendAccrual.id.desc()).limit(60)).scalars().all()
    payouts = db.execute(select(dv.PayoutRequest).order_by(dv.PayoutRequest.id.desc()).limit(60)).scalars().all()
    from datetime import timedelta as _td147
    from app.core.tz import now as _now147
    _t0 = _now147().replace(hour=0, minute=0, second=0, microsecond=0)
    _rev = dv.revenue_for(db, _t0 - _td147(days=1), _t0)
    _pp = int(_gs(db, "dividend_pool_percent", "30") or 0)
    _tot = sum(p.share_percent or 0 for p in partners if p.status == "active")
    return _t138.TemplateResponse(request, "ops_dividends.html", {
        "user": u, "msg": msg,
        "pool_percent": _gs(db, "dividend_pool_percent", "30"),
        "calc": {"revenue": _rev, "pool": _rev * _pp // 100, "total_shares": _tot},
        "partners": partners, "accruals": accruals, "payouts": payouts})

@router.post("/dividends/settings")
async def dividends_settings(request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    form = await request.form()
    from app.core.settings_svc import set_setting as _ss
    v = (form.get("dividend_pool_percent") or "30").strip()
    try:
        v = str(max(0, min(100, int(v))))
    except ValueError:
        v = "30"
    _ss(db, "dividend_pool_percent", v)
    db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=settings-ok", status_code=303)

@router.post("/dividends/partners")
async def dividends_partner_add(request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    form = await request.form()
    from app.services import dividends as dv
    dv.ensure_tables()
    from app.models import User
    from app.core.security import normalize_email
    email = (form.get("email") or "").strip()
    uid = None
    if email:
        usr = db.execute(select(User).where(User.email == normalize_email(email))).scalar_one_or_none()
        uid = usr.id if usr else None
    db.add(dv.PartnerShare(
        user_id=uid,
        title=(form.get("title") or email or "Партнёр").strip()[:120],
        invested_minor=int((form.get("invested") or "0").replace(".", "").replace(",", ".") and
                           float((form.get("invested") or "0").replace(",", ".")) * 100 or 0),
        share_percent=max(0, min(100, int(form.get("share") or 0))),
        status="active"))
    db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=partner-ok", status_code=303)

@router.post("/dividends/payouts/{pid}/approve")
def dividend_payout_approve(pid: int, request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.services import dividends as dv
    pr = db.get(dv.PayoutRequest, pid)
    if pr is not None and pr.status == "pending":
        partner = db.get(dv.PartnerShare, pr.partner_id)
        if partner is not None and partner.user_id:
            from app.models import User
            usr = db.get(User, partner.user_id)
            if usr is not None:
                w = ledger.get_wallet(db, usr.id)
                try:
                    ledger.debit(db, w, pr.amount_minor, reason="dividend_payout",
                                 entity_type="payout", entity_id=pr.id,
                                 idempotency_key=f"payout:{pr.id}")
                except Exception:
                    return RedirectResponse("/admin-ops/dividends?msg=payout-no-funds", status_code=303)
        pr.status = "paid"
        from app.core.tz import now as _n
        pr.paid_at = _n()
        db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=payout-ok", status_code=303)

@router.post("/dividends/payouts/{pid}/reject")
def dividend_payout_reject(pid: int, request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.services import dividends as dv
    pr = db.get(dv.PayoutRequest, pid)
    if pr is not None and pr.status == "pending":
        pr.status = "rejected"
        db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=payout-rejected", status_code=303)


@router.get("/ads/toggle")
def ads_toggle144(request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.core.settings_svc import get_setting as _g, set_setting as _s
    cur = _g(db, "invest_ads_enabled", "1")
    _s(db, "invest_ads_enabled", "0" if cur == "1" else "1")
    db.commit()
    return RedirectResponse("/admin-ops/", status_code=303)


@router.post("/dividends/partners/{pid}/toggle")
def partner_toggle147(pid: int, request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.services import dividends as dv
    p = db.get(dv.PartnerShare, pid)
    if p is not None:
        p.status = "disabled" if p.status == "active" else "active"
        db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=partner-toggled", status_code=303)

@router.post("/dividends/partners/{pid}/delete")
def partner_delete147(pid: int, request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.services import dividends as dv
    p = db.get(dv.PartnerShare, pid)
    if p is not None:
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin-ops/dividends?msg=partner-deleted", status_code=303)

@router.get("/docs", response_class=HTMLResponse)
def ops_docs_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    from app.core.settings_svc import get_setting as _g
    docs = {}
    for key, path in (("offer", "docs/legal/offer_template.md"),
                      ("terms", "docs/legal/terms.md"),
                      ("privacy", "docs/legal/privacy.md"),
                      ("dividends", "docs/dividends.md")):
        val = _g(db, "doc_" + key, "") or ""
        if not val:
            try:
                val = open(path).read()
            except OSError:
                val = ""
        docs[key] = val
    return _t138.TemplateResponse(request, "ops_docs.html",
                                  {"user": u, "msg": msg, "docs": docs})

@router.post("/docs")
async def ops_docs_save(request: Request, db: Session = Depends(get_db)):
    from app.ui.cabinet import _current_user as _cu
    u = _cu(db, request)
    if u is None or u.role != "admin":
        raise HTTPException(status_code=403)
    form = await request.form()
    from app.core.settings_svc import set_setting as _s
    for key in ("offer", "terms", "privacy", "dividends"):
        v = form.get("doc_" + key)
        if v is not None:
            _s(db, "doc_" + key, str(v))
    db.commit()
    return RedirectResponse("/admin-ops/docs?msg=saved", status_code=303)
