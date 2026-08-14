"""Tests for the brokerage router. Mocks core.snaptrade_client entirely so
nothing hits SnapTrade's real API - same isolated-DB approach as
test_auth.py.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import api
from core.db import Base, get_db
from core.models import PortfolioDigest
from core.models_db import AuditLogEntry
from core.routers.brokerage import PortfolioBalance, PortfolioPosition, PortfolioResponse, _build_digest_context

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def isolated_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    api.app.dependency_overrides[get_db] = override_get_db
    yield TestingSessionLocal
    api.app.dependency_overrides.pop(get_db, None)
    client.cookies.clear()


@pytest.fixture(autouse=True)
def logged_in_user():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    yield
    client.post("/auth/logout")


@pytest.fixture(autouse=True)
def mock_day_change():
    with patch("core.routers.brokerage.get_day_change") as mock:
        mock.return_value = {"percent": 1.5, "absolute": 2.0, "extended_hours": None}
        yield mock


def test_connect_requires_authentication():
    client.cookies.clear()
    response = client.post("/brokerage/connect")
    assert response.status_code == 401


@patch("core.routers.brokerage.snaptrade.request_connection_portal_url")
def test_connect_returns_portal_redirect_uri(mock_portal):
    mock_portal.return_value = {"redirect_uri": "https://app.snaptrade.com/portal/abc", "session_id": "sess-1"}
    response = client.post("/brokerage/connect")
    assert response.status_code == 200
    assert response.json() == {"redirect_uri": "https://app.snaptrade.com/portal/abc"}
    mock_portal.assert_called_once_with(custom_redirect=None)


def test_list_connections_starts_empty():
    response = client.get("/brokerage/connections")
    assert response.status_code == 200
    assert response.json() == []


@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_sync_pulls_in_remote_connections_and_accounts(mock_list_connections, mock_list_accounts):
    mock_list_connections.return_value = [
        {"id": "conn-1", "brokerage_name": "Schwab", "type": "read", "disabled": False}
    ]
    mock_list_accounts.return_value = [
        {"id": "acct-1", "name": "Individual", "number_last4": "1234"}
    ]

    response = client.post("/brokerage/sync")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["brokerage_name"] == "Schwab"
    assert body[0]["status"] == "active"
    assert body[0]["accounts"] == [
        {"id": 1, "snaptrade_account_id": "acct-1", "name": "Individual", "number_last4": "1234"}
    ]


@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_sync_marks_disabled_remote_connections_as_revoked(mock_list_connections, mock_list_accounts):
    mock_list_connections.return_value = [
        {"id": "conn-1", "brokerage_name": "Schwab", "type": "read", "disabled": True}
    ]
    mock_list_accounts.return_value = []

    response = client.post("/brokerage/sync")
    assert response.json()[0]["status"] == "revoked"


@patch("core.routers.brokerage.snaptrade.delete_connection")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_disconnect_removes_connection_and_calls_snaptrade(
    mock_list_connections, mock_list_accounts, mock_delete
):
    mock_list_connections.return_value = [
        {"id": "conn-1", "brokerage_name": "Schwab", "type": "read", "disabled": False}
    ]
    mock_list_accounts.return_value = []
    connection_id = client.post("/brokerage/sync").json()[0]["id"]

    response = client.delete(f"/brokerage/connections/{connection_id}")
    assert response.status_code == 200
    mock_delete.assert_called_once_with("conn-1")
    assert client.get("/brokerage/connections").json() == []


def test_disconnect_unknown_connection_returns_404():
    response = client.delete("/brokerage/connections/999")
    assert response.status_code == 404


@patch("core.routers.brokerage.snaptrade.request_connection_portal_url")
def test_connections_are_scoped_to_the_owning_user(mock_portal):
    mock_portal.return_value = {"redirect_uri": "https://example.com", "session_id": "sess-1"}
    client.post("/brokerage/connect")
    client.post("/auth/logout")

    client.post("/auth/signup", json={"email": "other@example.com", "password": "hunter22"})
    assert client.get("/brokerage/connections").json() == []


def _sync_one_account(mock_list_connections, mock_list_accounts) -> int:
    mock_list_connections.return_value = [
        {"id": "conn-1", "brokerage_name": "Schwab", "type": "read", "disabled": False}
    ]
    mock_list_accounts.return_value = [{"id": "acct-1", "name": "Individual", "number_last4": "1234"}]
    return client.post("/brokerage/sync").json()[0]["accounts"][0]["id"]


@patch("core.routers.brokerage.snaptrade.get_account_positions")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_get_positions_returns_snaptrade_data_and_logs_audit_event(
    mock_list_connections, mock_list_accounts, mock_positions, isolated_db
):
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    mock_positions.return_value = [
        {"symbol": "NVDA", "description": "NVIDIA Corp", "units": 1.5, "price": 200.0, "cost_basis": 180.0, "currency": "USD"}
    ]

    response = client.get(f"/brokerage/accounts/{account_id}/positions")
    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "NVDA"
    mock_positions.assert_called_once_with("acct-1")

    db = isolated_db()
    events = [e.event_type for e in db.query(AuditLogEntry).all()]
    assert "positions_viewed" in events
    db.close()


@patch("core.routers.brokerage.snaptrade.get_account_balances")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_get_balances_returns_snaptrade_data(mock_list_connections, mock_list_accounts, mock_balances):
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    mock_balances.return_value = [{"currency": "USD", "cash": 100.0, "buying_power": 100.0}]

    response = client.get(f"/brokerage/accounts/{account_id}/balances")
    assert response.status_code == 200
    assert response.json() == [{"currency": "USD", "cash": 100.0, "buying_power": 100.0}]


@patch("core.routers.brokerage.snaptrade.get_account_activities")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_get_transactions_returns_snaptrade_data(mock_list_connections, mock_list_accounts, mock_activities):
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    mock_activities.return_value = [
        {
            "id": "act-1",
            "type": "BUY",
            "description": "buy 1 share of NVDA",
            "symbol": "NVDA",
            "amount": -200.0,
            "units": 1.0,
            "price": 200.0,
            "currency": "USD",
            "trade_date": "2026-01-01T00:00:00Z",
        }
    ]

    response = client.get(f"/brokerage/accounts/{account_id}/transactions")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "act-1"


@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_positions_for_unowned_account_returns_404(mock_list_connections, mock_list_accounts):
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    client.post("/auth/logout")
    client.post("/auth/signup", json={"email": "other@example.com", "password": "hunter22"})

    response = client.get(f"/brokerage/accounts/{account_id}/positions")
    assert response.status_code == 404


def test_positions_for_unknown_account_returns_404():
    response = client.get("/brokerage/accounts/999/positions")
    assert response.status_code == 404


@patch("core.routers.brokerage.snaptrade.get_account_balances")
@patch("core.routers.brokerage.snaptrade.get_account_positions")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_portfolio_combines_positions_across_accounts_by_symbol(
    mock_list_connections, mock_list_accounts, mock_positions, mock_balances
):
    mock_list_connections.return_value = [
        {"id": "conn-1", "brokerage_name": "Schwab", "type": "read", "disabled": False},
        {"id": "conn-2", "brokerage_name": "Robinhood", "type": "read", "disabled": False},
    ]
    mock_list_accounts.side_effect = [
        [{"id": "acct-1", "name": "Schwab Individual", "number_last4": "1111"}],
        [{"id": "acct-2", "name": "Robinhood Individual", "number_last4": "2222"}],
    ]
    client.post("/brokerage/sync")

    mock_positions.side_effect = lambda account_id: {
        "acct-1": [{"symbol": "NVDA", "description": "NVIDIA Corp", "units": 1.0, "price": 100.0, "cost_basis": 80.0, "currency": "USD"}],
        "acct-2": [{"symbol": "NVDA", "description": "NVIDIA Corp", "units": 2.0, "price": 100.0, "cost_basis": 150.0, "currency": "USD"}],
    }[account_id]
    mock_balances.side_effect = lambda account_id: {
        "acct-1": [{"currency": "USD", "cash": 10.0, "buying_power": 10.0}],
        "acct-2": [{"currency": "USD", "cash": 5.0, "buying_power": 5.0}],
    }[account_id]

    response = client.get("/brokerage/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["balances"] == [{"currency": "USD", "cash": 15.0, "buying_power": 15.0}]
    assert body["positions"] == [
        {
            "symbol": "NVDA", "description": "NVIDIA Corp", "units": 3.0, "value": 300.0,
            "price_change": 2.0, "price_change_percent": 1.5, "extended_hours": None,
            "total_cost_basis": 380.0, "currency": "USD",
        }
    ]
    assert body["total_value"] == 315.0


def test_portfolio_is_empty_with_no_connections():
    response = client.get("/brokerage/portfolio")
    assert response.status_code == 200
    assert response.json() == {"total_value": 0.0, "balances": [], "positions": []}


@patch("core.routers.brokerage.snaptrade.get_account_positions")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_positions_get_none_price_change_when_day_change_lookup_fails(
    mock_list_connections, mock_list_accounts, mock_positions, mock_day_change
):
    mock_day_change.side_effect = ValueError("No day change found")
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    mock_positions.return_value = [
        {"symbol": "WEIRD.A", "description": None, "units": 1.0, "price": 10.0, "cost_basis": None, "currency": "USD"}
    ]

    response = client.get(f"/brokerage/accounts/{account_id}/positions")
    assert response.status_code == 200
    assert response.json()[0]["price_change"] is None
    assert response.json()[0]["price_change_percent"] is None


def test_digest_with_no_positions_returns_400():
    response = client.post("/brokerage/digest")
    assert response.status_code == 400


@patch("core.routers.brokerage.get_portfolio_digest")
@patch("core.routers.brokerage.get_market_news")
@patch("core.routers.brokerage.snaptrade.get_account_balances")
@patch("core.routers.brokerage.snaptrade.get_account_positions")
@patch("core.routers.brokerage.snaptrade.list_connection_accounts")
@patch("core.routers.brokerage.snaptrade.list_connections")
def test_digest_generates_article_and_logs_audit_event(
    mock_list_connections, mock_list_accounts, mock_positions, mock_balances, mock_news, mock_digest, isolated_db
):
    account_id = _sync_one_account(mock_list_connections, mock_list_accounts)
    mock_positions.return_value = [
        {"symbol": "NVDA", "description": "NVIDIA Corp", "units": 1.0, "price": 200.0, "cost_basis": 180.0, "currency": "USD"}
    ]
    mock_balances.return_value = [{"currency": "USD", "cash": 0.0, "buying_power": 0.0}]
    mock_news.return_value = [
        {
            "title": "NVDA rallies",
            "summary": "Chips are up.",
            "publisher": "Reuters",
            "url": "https://example.com/a",
            "published_at": "2026-08-13T12:00:00Z",
            "thumbnail": None,
            "ticker": "NVDA",
            "ticker_day_change_percent": 1.5,
            "related_tickers": [],
            "likely_unreadable": False,
        }
    ]
    mock_digest.return_value = PortfolioDigest(
        headline="NVDA leads a strong day",
        article="Paragraph one.\n\nParagraph two [1].",
        key_drivers=["NVDA up on chip demand [1]"],
        watch_items=["Upcoming earnings"],
    )

    response = client.post("/brokerage/digest")
    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "NVDA leads a strong day"
    assert body["key_drivers"] == ["NVDA up on chip demand [1]"]
    assert body["sources"] == [
        {"index": 1, "ticker": "NVDA", "title": "NVDA rallies", "publisher": "Reuters", "url": "https://example.com/a"}
    ]
    assert "generated_at" in body

    _, kwargs = mock_digest.call_args
    assert kwargs["user_id"] is not None
    assert kwargs["db"] is not None
    mock_digest.assert_called_once()

    db = isolated_db()
    events = [e.event_type for e in db.query(AuditLogEntry).all()]
    assert "digest_generated" in events
    db.close()


@patch("core.routers.brokerage._try_scrape_for_digest", return_value=None)
@patch("core.routers.brokerage.get_market_news")
def test_build_digest_context_numbers_sources_in_order(mock_news, mock_scrape):
    mock_news.return_value = [
        {
            "title": "NVDA rallies", "summary": "Chips are up.", "publisher": "Reuters",
            "url": "https://example.com/a", "published_at": "2026-08-13T12:00:00Z", "thumbnail": None,
            "ticker": "NVDA", "ticker_day_change_percent": 1.5, "related_tickers": [], "likely_unreadable": False,
        },
        {
            "title": "AAPL slips", "summary": "Supply concerns.", "publisher": "Bloomberg",
            "url": "https://example.com/b", "published_at": "2026-08-13T12:00:00Z", "thumbnail": None,
            "ticker": "AAPL", "ticker_day_change_percent": -0.5, "related_tickers": [], "likely_unreadable": False,
        },
    ]
    portfolio = PortfolioResponse(
        total_value=100.0,
        balances=[PortfolioBalance(currency="USD", cash=0.0, buying_power=0.0)],
        positions=[
            PortfolioPosition(
                symbol="NVDA", description="NVIDIA Corp", units=1.0, value=100.0,
                price_change=2.0, price_change_percent=1.5, total_cost_basis=80.0, currency="USD",
            )
        ],
    )

    context, sources = _build_digest_context(portfolio)

    assert "[1]" in context and "[2]" in context
    assert [s.model_dump() for s in sources] == [
        {"index": 1, "ticker": "NVDA", "title": "NVDA rallies", "publisher": "Reuters", "url": "https://example.com/a"},
        {"index": 2, "ticker": "AAPL", "title": "AAPL slips", "publisher": "Bloomberg", "url": "https://example.com/b"},
    ]
