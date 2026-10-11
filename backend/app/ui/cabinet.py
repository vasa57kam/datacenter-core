import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.vpn import get_adapter
from app.core import security
from app.db import get_db
from app.models import (
    LedgerEntry, Product, ServiceInstance, User, VpnAccount, VpnNode,
)
from app.services import ledger
from app.services.provisioning import enqueue_task

router = APIRouter(prefix="/lk", tags=["lk"])
public_router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="app/ui/templates")

SESSION_LONG = 30 * 24 * 3600     # «запомнить меня»
SESSION_SHORT = 12 * 3600         # без галочки — до конца дня

RU_STATUS = {
    "active": "активна",
    "suspended": "приостановлена",
    "provisioning": "выдаётся",
    "pending": "ожидает",
    "terminated": "завершена",
    "closed": "закрыта",
}
templates.env.filters["ru_status"] = lambda s: RU_STATUS.get(s, s)


def _session_alive(request: Request) -> bool:
    exp = request.session.get("exp")
    if not exp:
        return False
    if time.time() > int(exp):
        request.session.clear()
        return False
    return True


@public_router.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    products = db.execute(
        select(Product).where(Product.active.is_(True))
    ).scalars().all()
    return templates.TemplateResponse(request, "lk/landing.html", {"products": products})


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
    exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if exists is not None:
        return templates.TemplateResponse(
            request, "lk/register.html",
            {"error": "Email уже зарегистрирован"}, status_code=409,
        )
    user = User(email=email, password_hash=security.hash_password(password))
    db.add(user)
    db.flush()
    ledger.get_wallet(db, user.id)
    db.commit()
    return RedirectResponse("/lk/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "lk/login.html", {})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    remember: str = Form("on"),
    db: Session = Depends(get_db),
):
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not security.verify_password(password, user.password_hash) \
            or user.status != "active":
        raise HTTPException(status_code=401, detail="Bad credentials")
    request.session["uid"] = user.id
    request.session["exp"] = int(time.time()) + (SESSION_LONG if remember == "on" else SESSION_SHORT)
    return RedirectResponse("/lk/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/lk/login", status_code=303)


def _current_user(db: Session, request: Request):
    if not _session_alive(request):
        return None
    return db.get(User, int(request.session["uid"]))


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
    return templates.TemplateResponse(request, "lk/dashboard.html", {
        "user": user, "wallet": wallet, "entries": entries, "services": services,
    })


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
        cfg = get_adapter(node).render_config(db, account)
        link, sub_url, conf = cfg.get("link"), cfg.get("subscription_url"), cfg.get("config_text")
    return templates.TemplateResponse(request, "lk/config.html", {
        "user": user, "service": service, "link": link, "sub_url": sub_url, "conf": conf,
    })


@router.post("/services/{service_id}/suspend")
def service_suspend(service_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user is None:
        raise HTTPException(status_code=401)
    service = _own_service(db, user, service_id)
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
    wallet = ledger.get_wallet(db, user.id)
    if wallet.balance_minor <= 0:
        raise HTTPException(status_code=402, detail="Top up balance first")
    service.status = "active"
    enqueue_task(db, "service_instance", service.id, "resume")
    db.commit()
    return RedirectResponse("/lk/", status_code=303)
