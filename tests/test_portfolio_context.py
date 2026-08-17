"""Tests for core/portfolio_context.py. Mocks core.snaptrade_client and
core.tools.yf.Ticker so nothing hits SnapTrade or the network.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import tools
from core.db import Base
from core.models_db import BrokerageAccount, BrokerageConnection, User
from core.portfolio_context import build_portfolio_context


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="a@example.com", password_hash="x")
    session.add(user)
    session.commit()
    yield session, user.id
    session.close()


def _add_active_account(session, user_id, snaptrade_account_id="acc-1"):
    connection = BrokerageConnection(user_id=user_id, status="active", snaptrade_connection_id="conn-1")
    session.add(connection)
    session.commit()
    account = BrokerageAccount(connection_id=connection.id, snaptrade_account_id=snaptrade_account_id)
    session.add(account)
    session.commit()
    return account


def test_build_portfolio_context_returns_none_without_active_connection(db):
    session, user_id = db
    assert build_portfolio_context(session, user_id, "NVDA") is None


@patch("core.portfolio_context.snaptrade.get_account_positions")
def test_build_portfolio_context_returns_cash_message_when_flat(mock_positions, db):
    session, user_id = db
    _add_active_account(session, user_id)
    mock_positions.return_value = []

    context = build_portfolio_context(session, user_id, "NVDA")

    assert context.is_held is False
    assert context.summary == "The user's brokerage is connected but currently holds no positions (100% cash)."


@patch("core.tools.yf.Ticker")
@patch("core.portfolio_context.snaptrade.get_account_positions")
def test_build_portfolio_context_includes_weights_and_sectors(mock_positions, mock_ticker_cls, db):
    session, user_id = db
    _add_active_account(session, user_id)
    mock_positions.return_value = [
        {"symbol": "AMD", "description": "AMD", "units": 10.0, "price": 150.0, "cost_basis": 100.0, "currency": "USD"},
        {"symbol": "AAPL", "description": "Apple", "units": 5.0, "price": 200.0, "cost_basis": 150.0, "currency": "USD"},
    ]

    def ticker_side_effect(symbol):
        sectors = {"AMD": "Technology", "AAPL": "Technology", "NVDA": "Technology"}
        mock_ticker = MagicMock()
        mock_ticker.info = {"sector": sectors.get(symbol, "Unknown")}
        return mock_ticker

    mock_ticker_cls.side_effect = ticker_side_effect

    context = build_portfolio_context(session, user_id, "NVDA")

    # AMD: 10*150=1500, AAPL: 5*200=1000, total=2500
    assert context.is_held is False
    assert "Portfolio total value: $2,500" in context.summary
    assert "AMD: 60.0% of portfolio" in context.summary
    assert "AAPL: 40.0% of portfolio" in context.summary
    assert "Technology: 100.0%" in context.summary
    assert "NVDA is in the Technology sector and is not currently held." in context.summary


@patch("core.tools.yf.Ticker")
@patch("core.portfolio_context.snaptrade.get_account_positions")
def test_build_portfolio_context_flags_existing_holding(mock_positions, mock_ticker_cls, db):
    session, user_id = db
    _add_active_account(session, user_id)
    mock_positions.return_value = [
        {"symbol": "NVDA", "description": "Nvidia", "units": 4.0, "price": 250.0, "cost_basis": 100.0, "currency": "USD"},
    ]
    mock_ticker_cls.return_value = MagicMock(info={"sector": "Technology"})

    context = build_portfolio_context(session, user_id, "NVDA")

    assert context.is_held is True
    assert "NVDA is in the Technology sector and is already 100.0% of the portfolio." in context.summary
