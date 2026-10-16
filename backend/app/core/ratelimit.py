"""Простой rate limiter: 120 запросов/мин с IP на /lk и /api."""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_BUCKETS: dict = {}
LIMIT = 120
WINDOW = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/lk") or path.startswith("/api"):
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            b = _BUCKETS.setdefault(ip, [])
            b[:] = [t for t in b if now - t < WINDOW]
            if len(b) >= LIMIT:
                return JSONResponse({"detail": "too many requests"}, status_code=429)
            b.append(now)
        return await call_next(request)
