import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
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
    if r:
        return r
    return templates.TemplateResponse(request, "ops/home.html", {})


@router.get("/nodes/import", response_class=HTMLResponse)
def import_page(request: Request, error: str = "", ok: str = ""):
    r = _guard(request)
    if r:
        return r
    return templates.TemplateResponse(request, "ops/import_node.html", {"error": error, "ok": ok, "inbound_json": ""})


@router.post("/nodes/import")
def import_submit(
    request: Request,
    inbound_json: str = Form(),
    inbound_id: int = Form(0),
    code: str = Form(""),
    name: str = Form(""),
    country: str = Form("NL"),
    endpoint_host: str = Form(""),
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
        )
        db.commit()
        return RedirectResponse(f"/admin-ops/nodes/import?ok=Нода+{node.code}+создана+inbound+{node.extra.get('inbound_id')}+порт+{node.endpoint_port}", status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            request, "ops/import_node.html",
            {"error": str(e), "ok": "", "inbound_json": inbound_json}, status_code=400,
        )


@router.get("/tariffs", response_class=HTMLResponse)
def tariffs_page(request: Request, error: str = "", ok: str = ""):
    r = _guard(request)
    if r:
        return r
    return templates.TemplateResponse(request, "ops/tariffs.html", {"error": error, "ok": ok, "units": UNITS})


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
        prices = {"second": price_second, "minute": price_minute, "gb": price_gb, "month": price_month}
        res = ensure_tariffs(db, protocol.strip() or "vless", country.strip() or "NL", prices)
        db.commit()
        created = sum(1 for x in res if x["created"])
        return RedirectResponse(f"/admin-ops/tariffs?ok=Готово+создано+{created}+обновлено+{len(res)-created}", status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            request, "ops/tariffs.html",
            {"error": str(e), "ok": "", "units": UNITS}, status_code=400,
        )
