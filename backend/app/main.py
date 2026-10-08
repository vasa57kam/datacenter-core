from fastapi import FastAPI

from app.api.internal import cctv as internal_cctv
from app.api.internal import vpn as internal_vpn
from app.api.v1 import admin, auth, products, services, wallet

app = FastAPI(title="ITKAM34 Billing Core", version="0.2.0")

for router in (
    auth.router,
    products.router,
    wallet.router,
    services.router,
    admin.router,
    internal_vpn.router,
    internal_cctv.router,
):
    app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}