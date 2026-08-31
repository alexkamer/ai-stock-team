"""SQLAlchemy ORM models (persisted state). Distinct from core/models.py,
which holds Pydantic API request/response shapes, not database tables.
"""

import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
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
    brokerage_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
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


class TeamVerdictRecord(Base):
    """One logged Stock Team verdict, at most one per (user, ticker,
    call_date) - regenerating the same ticker again the same day just
    refreshes the on-screen view, it doesn't add a second row (see
    core/track_record.py, which owns the dedupe-on-insert and the later
    scoring against real historical prices)."""

    __tablename__ = "team_verdicts"
    __table_args__ = (UniqueConstraint("user_id", "ticker", "call_date", name="uq_team_verdict_per_ticker_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    verdict: Mapped[str] = mapped_column(String(8))
    key_factors: Mapped[str] = mapped_column(Text())
    reasoning: Mapped[str] = mapped_column(Text())
    price_at_call: Mapped[float] = mapped_column(Float())
    # Nullable: rows logged before this field existed have no prediction to
    # backfill, not just a missing value - None is the honest state for them.
    predicted_price: Mapped[float | None] = mapped_column(Float(), nullable=True)
    predicted_horizon: Mapped[str | None] = mapped_column(String(8), nullable=True)
    call_date: Mapped[date] = mapped_column(Date(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    specialist_calls: Mapped[list["SpecialistCallRecord"]] = relationship(
        back_populates="team_verdict", cascade="all, delete-orphan"
    )


class SpecialistCallRecord(Base):
    """One specialist's signal on a given TeamVerdictRecord, for calibrating
    that specialist's own accuracy over time (see core/track_record.py).

    0-6 rows per verdict, not always 6 - the synthesizer decides which
    specialist tools to call, and the no-brokerage portfolio_fit fallback
    (a canned response, not a real judgment) is deliberately never recorded
    here."""

    __tablename__ = "specialist_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_verdict_id: Mapped[int] = mapped_column(ForeignKey("team_verdicts.id"), index=True)
    specialist_key: Mapped[str] = mapped_column(String(32), index=True)
    signal: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    team_verdict: Mapped["TeamVerdictRecord"] = relationship(back_populates="specialist_calls")


class ThemePortfolio(Base):
    """One thematic allocation run - the Themes tab's version of
    TeamVerdictRecord, but for a basket of picks rather than a single
    ticker's verdict. `method` distinguishes a no-LLM "formula" run (pure
    momentum/market-cap ranking) from an "ai_team" run (full multi-agent
    vetting + a conviction-weighted allocator agent) - see
    agents/theme_builder.py."""

    __tablename__ = "theme_portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    theme_key: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Float())
    summary: Mapped[str] = mapped_column(Text())
    method: Mapped[str] = mapped_column(String(16), default="ai_team")
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)

    picks: Mapped[list["ThemePortfolioPick"]] = relationship(
        back_populates="theme_portfolio", cascade="all, delete-orphan"
    )


class ThemePortfolioPick(Base):
    """One stock's slice of a ThemePortfolio - weight/dollar amount/shares
    are the Python-computed values (see agents/theme_builder.py), not raw
    LLM output, so they're trustworthy arithmetic rather than a model guess.
    `verdict` is nullable: a "formula" method pick was never vetted for a
    buy/hold/sell call, so None here is the honest state for it (not a
    missing value)."""

    __tablename__ = "theme_portfolio_picks"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_portfolio_id: Mapped[int] = mapped_column(ForeignKey("theme_portfolios.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    weight_percent: Mapped[float] = mapped_column(Float())
    dollar_amount: Mapped[float] = mapped_column(Float())
    shares: Mapped[float] = mapped_column(Float())
    rationale: Mapped[str] = mapped_column(Text())

    theme_portfolio: Mapped["ThemePortfolio"] = relationship(back_populates="picks")


class LlmCallLog(Base):
    """One row per LLM call whose caller has a DB session - real per-call
    cost via genai_prices, not an estimate. user_id is nullable since some
    future call sites may be anonymous (public/unauthenticated routes)."""

    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    call_site: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    requests: Mapped[int] = mapped_column(default=1)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float())
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)
