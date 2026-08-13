"""Connect/list/disconnect brokerage connections via SnapTrade.

Every route here is behind get_current_user. Note the Personal-key caveat
from models_db.BrokerageConnection: SnapTrade itself doesn't scope
connections by app user (there's one SnapTrade identity for the whole
app), so `user_id` on a row is about who in *our* app can see/manage it,
not brokerage-level isolation.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

import core.snaptrade_client as snaptrade
from core.audit import log_event
from core.auth import get_current_user
from core.db import get_db
from core.models_db import BrokerageAccount, BrokerageConnection, User
from core.tools import get_day_change, parallel_map

router = APIRouter(prefix="/brokerage", tags=["brokerage"])


class ConnectRequest(BaseModel):
    custom_redirect: str | None = None


class ConnectResponse(BaseModel):
    redirect_uri: str


class AccountResponse(BaseModel):
    id: int
    snaptrade_account_id: str
    name: str | None
    number_last4: str | None


class ConnectionResponse(BaseModel):
    id: int
    brokerage_name: str | None
    status: str
    accounts: list[AccountResponse]


class PositionResponse(BaseModel):
    symbol: str
    description: str | None
    units: float
    price: float
    price_change: float | None  # per-share $ change today, from yfinance - SnapTrade has no day-change field
    price_change_percent: float | None
    cost_basis: float | None  # per-unit average cost, as SnapTrade returns it - NOT the position total
    currency: str | None


class BalanceResponse(BaseModel):
    currency: str
    cash: float
    buying_power: float


class ActivityResponse(BaseModel):
    id: str
    type: str | None
    description: str | None
    symbol: str | None
    amount: float | None
    units: float | None
    price: float | None
    currency: str | None
    trade_date: str | None


class PortfolioBalance(BaseModel):
    currency: str
    cash: float
    buying_power: float


class PortfolioPosition(BaseModel):
    symbol: str
    description: str | None
    units: float
    value: float
    price_change: float | None
    price_change_percent: float | None
    total_cost_basis: float | None  # sum of units * per-unit cost_basis across accounts - a total, unlike PositionResponse.cost_basis
    currency: str | None


class PortfolioResponse(BaseModel):
    total_value: float
    balances: list[PortfolioBalance]
    positions: list[PortfolioPosition]


@router.post("/connect", response_model=ConnectResponse)
def connect(
    body: ConnectRequest = ConnectRequest(),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    portal = snaptrade.request_connection_portal_url(custom_redirect=body.custom_redirect)
    connection = BrokerageConnection(
        user_id=user.id,
        portal_session_id=portal["session_id"],
        status="pending",
    )
    db.add(connection)
    db.commit()
    log_event(db, user.id, "brokerage_connect_requested")
    return ConnectResponse(redirect_uri=portal["redirect_uri"])


@router.post("/sync", response_model=list[ConnectionResponse])
def sync_connections(user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    """Pulls the latest connection/account list from SnapTrade and mirrors
    it into our DB. There's no per-user webhook target yet (Phase 3), so
    the frontend calls this right after returning from the portal, and a
    user can also call it manually to refresh."""
    remote_connections = snaptrade.list_connections()
    remote_by_id = {c["id"]: c for c in remote_connections}

    existing = db.query(BrokerageConnection).filter(
        BrokerageConnection.user_id == user.id,
        BrokerageConnection.snaptrade_connection_id.isnot(None),
    ).all()
    existing_by_remote_id = {c.snaptrade_connection_id: c for c in existing}

    # Claim any of our own still-"pending" rows (created by /connect, not yet
    # matched to a real SnapTrade connection id) for new remote connections.
    pending = db.query(BrokerageConnection).filter(
        BrokerageConnection.user_id == user.id,
        BrokerageConnection.snaptrade_connection_id.is_(None),
    ).all()
    unclaimed_remote_ids = [rid for rid in remote_by_id if rid not in existing_by_remote_id]
    for pending_row, remote_id in zip(pending, unclaimed_remote_ids):
        pending_row.snaptrade_connection_id = remote_id
        existing_by_remote_id[remote_id] = pending_row

    for remote_id, remote in remote_by_id.items():
        connection = existing_by_remote_id.get(remote_id)
        if connection is None:
            connection = BrokerageConnection(user_id=user.id, snaptrade_connection_id=remote_id)
            db.add(connection)
        connection.brokerage_name = remote["brokerage_name"]
        connection.status = "revoked" if remote["disabled"] else "active"

        remote_accounts = snaptrade.list_connection_accounts(remote_id)
        existing_accounts = {a.snaptrade_account_id: a for a in connection.accounts}
        for remote_account in remote_accounts:
            account = existing_accounts.get(remote_account["id"])
            if account is None:
                account = BrokerageAccount(snaptrade_account_id=remote_account["id"])
                connection.accounts.append(account)
            account.name = remote_account["name"]
            account.number_last4 = remote_account["number_last4"]

    db.commit()
    return _serialize_connections(
        db.query(BrokerageConnection).filter(BrokerageConnection.user_id == user.id).all()
    )


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    connections = db.query(BrokerageConnection).filter(BrokerageConnection.user_id == user.id).all()
    return _serialize_connections(connections)


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    """Combines positions/balances across every active account into one
    picture: total value, cash by currency, and positions deduped by
    symbol (summed across accounts/brokerages)."""
    accounts = (
        db.query(BrokerageAccount)
        .join(BrokerageConnection)
        .filter(BrokerageConnection.user_id == user.id, BrokerageConnection.status == "active")
        .all()
    )

    balances_by_currency: dict[str, dict] = {}
    positions_by_symbol: dict[str, dict] = {}

    for account in accounts:
        for balance in snaptrade.get_account_balances(account.snaptrade_account_id):
            agg = balances_by_currency.setdefault(balance["currency"], {"cash": 0.0, "buying_power": 0.0})
            agg["cash"] += balance["cash"]
            agg["buying_power"] += balance["buying_power"]

        for position in snaptrade.get_account_positions(account.snaptrade_account_id):
            agg = positions_by_symbol.setdefault(
                position["symbol"],
                {"description": position["description"], "units": 0.0, "value": 0.0,
                 "total_cost_basis": 0.0, "currency": position["currency"]},
            )
            agg["units"] += position["units"]
            agg["value"] += position["units"] * position["price"]
            # cost_basis from SnapTrade is per-unit, not a total - multiply by
            # this position's units before summing across accounts/symbols.
            if position["cost_basis"] is not None and agg["total_cost_basis"] is not None:
                agg["total_cost_basis"] += position["units"] * position["cost_basis"]
            else:
                agg["total_cost_basis"] = None

    total_value = sum(b["cash"] for b in balances_by_currency.values()) + sum(
        p["value"] for p in positions_by_symbol.values()
    )

    combined_positions = _with_day_change(
        [{"symbol": symbol, **agg} for symbol, agg in positions_by_symbol.items()]
    )

    log_event(db, user.id, "portfolio_viewed")

    return PortfolioResponse(
        total_value=total_value,
        balances=[PortfolioBalance(currency=currency, **agg) for currency, agg in balances_by_currency.items()],
        positions=[PortfolioPosition(**position) for position in combined_positions],
    )


@router.delete("/connections/{connection_id}")
def disconnect(
    connection_id: int, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
):
    connection = db.get(BrokerageConnection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")

    if connection.snaptrade_connection_id:
        snaptrade.delete_connection(connection.snaptrade_connection_id)
    brokerage_name = connection.brokerage_name
    db.delete(connection)
    db.commit()
    log_event(db, user.id, "brokerage_disconnected", detail=brokerage_name)
    return {"ok": True}


def _day_change_or_none(symbol: str) -> dict:
    try:
        change = get_day_change(symbol)
        return {"price_change": change["absolute"], "price_change_percent": change["percent"]}
    except Exception:
        return {"price_change": None, "price_change_percent": None}


def _with_day_change(positions: list[dict]) -> list[dict]:
    """Adds price_change/price_change_percent from tools.get_day_change
    (yfinance) - SnapTrade's position data has no day-change field at
    all. Fetched concurrently (parallel_map) since a large portfolio can
    have 50+ distinct symbols and these are sequential network round-trips
    otherwise; a symbol yfinance doesn't recognize just gets None rather
    than failing the whole positions response."""
    symbols = list(dict.fromkeys(position["symbol"] for position in positions))
    changes = dict(zip(symbols, parallel_map(_day_change_or_none, symbols)))
    for position in positions:
        position.update(changes[position["symbol"]])
    return positions


def _get_owned_account(db: DbSession, user: User, account_id: int) -> BrokerageAccount:
    """Our own DB is the only thing enforcing per-user isolation here -
    SnapTrade's Personal key has no concept of which app user an account
    belongs to (see module docstring), so this check is load-bearing, not
    a nice-to-have."""
    account = db.get(BrokerageAccount, account_id)
    if account is None or account.connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/accounts/{account_id}/positions", response_model=list[PositionResponse])
def get_positions(account_id: int, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    account = _get_owned_account(db, user, account_id)
    positions = _with_day_change(snaptrade.get_account_positions(account.snaptrade_account_id))
    log_event(db, user.id, "positions_viewed", detail=f"account_id={account_id}")
    return positions


@router.get("/accounts/{account_id}/balances", response_model=list[BalanceResponse])
def get_balances(account_id: int, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    account = _get_owned_account(db, user, account_id)
    balances = snaptrade.get_account_balances(account.snaptrade_account_id)
    log_event(db, user.id, "balances_viewed", detail=f"account_id={account_id}")
    return balances


@router.get("/accounts/{account_id}/transactions", response_model=list[ActivityResponse])
def get_transactions(account_id: int, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)):
    account = _get_owned_account(db, user, account_id)
    activities = snaptrade.get_account_activities(account.snaptrade_account_id)
    log_event(db, user.id, "transactions_viewed", detail=f"account_id={account_id}")
    return activities


def _serialize_connections(connections: list[BrokerageConnection]) -> list[ConnectionResponse]:
    return [
        ConnectionResponse(
            id=c.id,
            brokerage_name=c.brokerage_name,
            status=c.status,
            accounts=[
                AccountResponse(
                    id=a.id,
                    snaptrade_account_id=a.snaptrade_account_id,
                    name=a.name,
                    number_last4=a.number_last4,
                )
                for a in c.accounts
            ],
        )
        for c in connections
    ]
