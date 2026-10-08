import hmac
import secrets

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = security.decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="User inactive")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_internal_key(x_internal_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Bad internal key")