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
