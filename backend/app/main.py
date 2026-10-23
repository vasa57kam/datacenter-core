from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.internal import cctv as internal_cctv
from app.api.internal import vpn as internal_vpn
from app.api.v1 import admin, auth, products, quickops, services, wallet
from app.core.config import settings
from app.ui import cabinet, ops
from app.ui.admin import setup_admin
from app.ui.help import router as help_router

app = FastAPI(title="ITKAM34 Billing Core", version="0.7.3")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret,
    max_age=30 * 24 * 3600,
    same_site="lax",
)

for router in (
    cabinet.public_router,
    auth.router,
    products.router,
    wallet.router,
    services.router,
    admin.router,
    quickops.router,
    internal_vpn.router,
    internal_cctv.router,
    cabinet.router,
    ops.router,
    help_router,
):
    app.include_router(router)


from starlette.responses import RedirectResponse as _RR


@app.get("/admin", include_in_schema=False)
async def _admin_root_redirect():
    return _RR("/admin-ops/", status_code=302)


@app.get("/admin/", include_in_schema=False)
async def _admin_root_redirect_slash():
    return _RR("/admin-ops/", status_code=302)




@app.on_event("startup")
def _startup_guard():
    import threading
    def _run():
        import time as _t
        _t.sleep(20)
        try:
            from app.services.offline_guard import run_guard
            run_guard()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


setup_admin(app, secret_key=settings.jwt_secret)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


import re

# ---- v148: единая тема на все HTML-страницы (middleware) ----
from starlette.middleware.base import BaseHTTPMiddleware as _BHM148
from starlette.responses import Response as _Resp148

_THEME_CACHE148 = {}

def _theme148() -> str:
    if "css" not in _THEME_CACHE148:
        try:
            _THEME_CACHE148["css"] = open("app/ui/theme.css").read()
        except OSError:
            _THEME_CACHE148["css"] = ""
    return _THEME_CACHE148["css"]

class Theme148Middleware(_BHM148):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype:
            return resp
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk
        html = body.decode("utf-8", "ignore")
        need_theme = "<!--theme148-->" not in html
        need_vp = "name=\"viewport\"" not in html
        if need_theme or need_vp:
            ins = ""
            if need_vp:
                ins += '<meta name="viewport" content="width=device-width, initial-scale=1">'
            if need_theme:
                ins += "<!--theme148--><style>" + _theme148() + "</style>"
            if "</head>" in html:
                html = html.replace("</head>", ins + "</head>", 1)
            else:
                m = re.search(r"<body[^>]*>", html)
                if m:
                    html = html[:m.end()] + ins + html[m.end():]
                else:
                    html = ins + html
        new = _Resp148(content=html, status_code=resp.status_code,
                       media_type=resp.media_type or "text/html")
        for k, v in resp.headers.items():
            if k.lower() != "content-length":
                new.headers[k] = v
        return new

app.add_middleware(Theme148Middleware)
