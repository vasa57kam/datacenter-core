from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.internal import cctv as internal_cctv
from app.api.internal import debug as internal_debug
from app.api.internal import debug as internal_debug
from app.api.internal import vpn as internal_vpn
from app.api.v1 import admin, auth, products, services, wallet
from app.core.config import settings
from app.ui import cabinet
from app.ui.admin import setup_admin
from app.ui.help import router as help_router

app = FastAPI(title="ITKAM34 Billing Core", version="0.7.1")

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
    internal_vpn.router,
    internal_cctv.router,
    internal_debug.router,
    internal_debug.router,
    cabinet.router,
    help_router,
):
    app.include_router(router)

setup_admin(app, secret_key=settings.jwt_secret)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
