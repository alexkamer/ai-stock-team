"""Tests for chat.py. Overrides chat.agent's model with TestModel and mocks
yf.Ticker, same pattern as test_main.py/test_stock_team.py.
"""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from agents import chat
from core import tools


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


@pytest.fixture(autouse=True)
def clear_sessions():
    chat._sessions.clear()
    yield
    chat._sessions.clear()


def full_info():
    # TestModel fuzz-calls every registered tool, including get_market_cap,
    # get_pe_ratio, get_day_change, get_price_history, get_watchlist_prices -
    # all of them need a value present or they raise ValueError.
    return {
        "currentPrice": 132.45,
        "marketCap": 4.78e12,
        "trailingPE": 30.3,
        "longName": "NVIDIA Corporation",
        "regularMarketChangePercent": 1.8,
        "regularMarketChange": 2.34,
    }


def default_history():
    import pandas as pd

    return pd.DataFrame({"Close": [128.1, 129.4, 132.45], "High": [129.0, 130.0, 133.0], "Low": [127.0, 128.0, 131.0]})


@pytest.mark.asyncio
async def test_send_message_returns_reply():
    test_model = TestModel(custom_output_text="NVDA is currently $132.45.")

    with chat.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = full_info()
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        mock_ticker_cls.return_value.history.return_value = default_history()

        reply = await chat.send_message("session-1", "What's NVDA's price?")

    assert reply == "NVDA is currently $132.45."


@pytest.mark.asyncio
async def test_send_message_accumulates_history_per_session():
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = full_info()
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        mock_ticker_cls.return_value.history.return_value = default_history()

        assert "session-1" not in chat._sessions
        await chat.send_message("session-1", "First message")
        first_history_len = len(chat._sessions["session-1"])

        await chat.send_message("session-1", "Second message")
        second_history_len = len(chat._sessions["session-1"])

    assert second_history_len > first_history_len


@pytest.mark.asyncio
async def test_send_message_uses_passed_watchlist_over_the_default():
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = full_info()
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        mock_ticker_cls.return_value.history.return_value = default_history()

        await chat.send_message("session-1", "What's on my watchlist?", watchlist=["TSLA", "AMD"])

    # TestModel fuzz-calls get_watchlist_prices, which reads ctx.deps.tickers -
    # so a Ticker(...) lookup for the passed-in symbols, not the hardcoded
    # DEFAULT_WATCHLIST, confirms the custom watchlist actually reached the agent.
    queried_tickers = {call.args[0] for call in mock_ticker_cls.call_args_list}
    assert {"TSLA", "AMD"} <= queried_tickers
    assert "NVDA" not in queried_tickers


@pytest.mark.asyncio
async def test_send_message_falls_back_to_default_watchlist_when_none_given():
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = full_info()
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        mock_ticker_cls.return_value.history.return_value = default_history()

        await chat.send_message("session-1", "What's on my watchlist?")

    queried_tickers = {call.args[0] for call in mock_ticker_cls.call_args_list}
    assert set(chat.DEFAULT_WATCHLIST) <= queried_tickers


@pytest.mark.asyncio
async def test_send_message_keeps_sessions_isolated():
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = full_info()
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        mock_ticker_cls.return_value.history.return_value = default_history()

        await chat.send_message("session-a", "hi")
        await chat.send_message("session-b", "hi")

    assert chat._sessions["session-a"] is not chat._sessions["session-b"]
