"""Thin wrapper around the SnapTrade SDK - keeps SDK usage in one place,
mirroring how tools.py wraps yfinance elsewhere in this app.

Uses a Personal API key: there's no registerUser/userId/userSecret concept
(see BrokerageConnection's docstring in models_db.py) - every call below
implicitly operates on the single SnapTrade identity tied to our API key.

Deliberately read-only: connection_type="read" is always passed explicitly
when generating a portal URL, and no trade-execution SDK methods (order
placement, cancellation, etc.) are wrapped here at all - not "unused", but
genuinely absent, so there's no code path that could place a trade.
"""

import os
import re
from urllib.parse import urlparse

from snaptrade_client import SnapTrade
from snaptrade_client.auth import SnapTradeAuth

import core.env  # noqa: F401 - loads .env before the os.environ.get() calls below

_client: SnapTrade | None = None


def _domain_from_url(url: str | None) -> str | None:
    """SnapTrade's own S3 logo URLs are hotlink-protected and fail when
    loaded directly from the browser - same fix as TickerDetail's company
    logos, which resolve a domain through Google's favicon service instead
    of hosting/proxying logo images ourselves."""
    if not url:
        return None
    host = urlparse(url).netloc or urlparse(url).path
    return host.removeprefix("www.") or None


def _get_client() -> SnapTrade:
    global _client
    if _client is None:
        _client = SnapTrade(
            auth=SnapTradeAuth.personal_api_key(
                consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"],
                client_id=os.environ["SNAPTRADE_CLIENT_ID"],
            )
        )
    return _client


def request_connection_portal_url(custom_redirect: str | None = None) -> dict:
    """Returns {"redirect_uri", "session_id"} for the SnapTrade-hosted
    Connection Portal. connection_type="read" is non-negotiable here."""
    resp = _get_client().authentication.login_snap_trade_user(
        connection_type="read",
        custom_redirect=custom_redirect,
    )
    return {"redirect_uri": resp.body["redirectURI"], "session_id": resp.body["sessionId"]}


def list_connections() -> list[dict]:
    """All brokerage connections (authorizations) visible to our API key."""
    resp = _get_client().connections.list_brokerage_authorizations()
    return [
        {
            "id": item["id"],
            "brokerage_name": item["brokerage"].get("display_name") or item["brokerage"].get("name"),
            "brokerage_domain": _domain_from_url(item["brokerage"].get("url")),
            "type": item["type"],
            "disabled": item["disabled"],
        }
        for item in resp.body
    ]


def list_connection_accounts(connection_id: str) -> list[dict]:
    """Accounts under one connection. Account numbers from SnapTrade are
    NOT pre-masked for every brokerage - some are already masked display
    strings like "Individual ...282", others are full raw numbers - so
    this pulls out just the trailing digits rather than persisting
    `number` as-is."""
    resp = _get_client().connections.list_brokerage_authorization_accounts(authorization_id=connection_id)
    return [
        {
            "id": item["id"],
            "name": item.get("name"),
            "number_last4": re.sub(r"\D", "", item.get("number") or "")[-4:] or None,
        }
        for item in resp.body
    ]


def delete_connection(connection_id: str) -> None:
    _get_client().connections.delete_connection(connection_id=connection_id)


def get_account_positions(account_id: str) -> list[dict]:
    resp = _get_client().account_information.get_all_account_positions(account_id=account_id)
    return [
        {
            "symbol": item["instrument"]["symbol"],
            "description": item["instrument"].get("description"),
            "units": float(item["units"]),
            "price": float(item["price"]),
            "cost_basis": float(item["cost_basis"]) if item.get("cost_basis") is not None else None,
            "currency": item.get("currency"),
        }
        for item in resp.body["results"]
    ]


def get_account_balances(account_id: str) -> list[dict]:
    resp = _get_client().account_information.get_user_account_balance(account_id=account_id)
    return [
        {
            "currency": item["currency"]["code"],
            "cash": item["cash"],
            "buying_power": item["buying_power"],
        }
        for item in resp.body
    ]


def get_account_activities(account_id: str, limit: int = 50) -> list[dict]:
    resp = _get_client().account_information.get_account_activities(account_id=account_id, limit=limit)
    return [
        {
            "id": item["id"],
            "type": item.get("type"),
            "description": item.get("description"),
            "symbol": (item.get("symbol") or {}).get("symbol"),
            "amount": item.get("amount"),
            "units": item.get("units"),
            "price": item.get("price"),
            "currency": (item.get("currency") or {}).get("code"),
            "trade_date": item.get("trade_date"),
        }
        for item in resp.body["data"]
    ]
