"""Password hashing, session lifecycle, and the get_current_user dependency
that every authenticated route depends on.
"""

import os
from datetime import datetime, timezone

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from core.db import get_db
from core.models_db import User, UserSession


def _now() -> datetime:
    # Matches models_db._now(): naive UTC, since that's what SQLite hands
    # back on read regardless of what tzinfo was stored.
    return datetime.now(timezone.utc).replace(tzinfo=None)

SESSION_COOKIE_NAME = "session"

# Cookies only get the Secure flag when explicitly told we're behind HTTPS -
# turn this on once the app is hosted anywhere other than localhost.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# Off by default: a single fork-and-run instance has exactly one person
# using it, so login/signup is friction with no data-isolation benefit. Turn
# this on only if you're hosting one instance for more than one person.
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() == "true"

LOCAL_USER_EMAIL = "local@localhost"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session(db: DbSession, user: User) -> UserSession:
    session = UserSession(user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DbSession, token: str) -> UserSession | None:
    session = db.get(UserSession, token)
    if session is None:
        return None
    if session.expires_at < _now():
        db.delete(session)
        db.commit()
        return None
    return session


def delete_session(db: DbSession, token: str) -> None:
    session = db.get(UserSession, token)
    if session is not None:
        db.delete(session)
        db.commit()


def _get_or_create_local_user(db: DbSession) -> User:
    # BrokerageConnection.snaptrade_connection_id is globally unique - a
    # Personal SnapTrade API key backs exactly one real identity, so there
    # can only ever be one meaningful "local" owner. Reuse whichever user
    # already exists (e.g. an admin account seeded before AUTH_REQUIRED was
    # turned off) rather than minting a second one that would collide on
    # sync; only create local@localhost when the table is genuinely empty.
    user = db.query(User).order_by(User.id).first()
    if user is not None:
        return user
    user = User(email=LOCAL_USER_EMAIL, password_hash=hash_password(os.urandom(32).hex()))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> User:
    if not AUTH_REQUIRED:
        return _get_or_create_local_user(db)
    if session_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = get_session(db, session_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired")
    session.last_seen_at = _now()
    db.commit()
    return session.user
