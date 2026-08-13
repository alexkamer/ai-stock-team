"""Signup/login/logout/me - the whole account surface for now."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session as DbSession

from core.auth import (
    COOKIE_SECURE,
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    get_current_user,
    hash_password,
    verify_password,
)
from core.db import get_db
from core.models_db import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
        path="/",
    )


@router.post("/signup", response_model=UserResponse)
def signup(body: SignupRequest, response: Response, db: DbSession = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.email == body.email).first() is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    session = create_session(db, user)
    _set_session_cookie(response, session.id)
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, response: Response, db: DbSession = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    session = create_session(db, user)
    _set_session_cookie(response, session.id)
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if session_token is not None:
        delete_session(db, session_token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email)
