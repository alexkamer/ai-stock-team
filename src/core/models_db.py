"""SQLAlchemy ORM models (persisted state). Distinct from core/models.py,
which holds Pydantic API request/response shapes, not database tables.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base

SESSION_LIFETIME = timedelta(days=14)


def _now() -> datetime:
    # Naive UTC, not timezone-aware: SQLite silently drops tzinfo on
    # round-trip, so every datetime stored/compared here must be naive UTC
    # consistently (including in auth.py) or comparisons raise TypeError.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """A logged-in session, keyed by an opaque bearer token (also the
    cookie value) rather than a sequential id, since the id itself is the
    secret that authenticates the request."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: secrets.token_urlsafe(32))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), default=lambda: _now() + SESSION_LIFETIME)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    user: Mapped["User"] = relationship(back_populates="sessions")


class BrokerageConnection(Base):
    """A linked brokerage connection via SnapTrade.

    Our SnapTrade API key is a Personal key, which has no per-end-user
    registerUser/userSecret concept - the key itself is scoped to one
    SnapTrade identity (the app owner's). user_id here is who in *our* app
    initiated/owns visibility of the connection, kept for when/if this
    moves to a Commercial key with real per-user SnapTrade identities.
    """

    __tablename__ = "brokerage_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    snaptrade_connection_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    portal_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    brokerage_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    accounts: Mapped[list["BrokerageAccount"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class BrokerageAccount(Base):
    """One brokerage account under a BrokerageConnection. Only metadata is
    stored here - positions/balances/transactions are always fetched live
    from SnapTrade, never cached in our DB."""

    __tablename__ = "brokerage_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("brokerage_connections.id"), index=True)
    snaptrade_account_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    number_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    connection: Mapped["BrokerageConnection"] = relationship(back_populates="accounts")


class AuditLogEntry(Base):
    """One entry per connect/disconnect/data-access event - financial data
    warrants an access trail even at single-user scale."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)
