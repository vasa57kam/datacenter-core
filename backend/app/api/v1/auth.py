from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Wallet
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    exists = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email, password_hash=security.hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id, currency="RUB", balance_minor=0))
    db.commit()
    return TokenResponse(access_token=security.create_access_token(user.id, user.role))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Bad credentials")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User blocked")
    return TokenResponse(access_token=security.create_access_token(user.id, user.role))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user