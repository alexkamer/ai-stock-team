"""Tests for api.py. Mocks yf.Ticker so nothing hits the network."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from agents import chat, main, stock_team
from core import api, tools

client = TestClient(api.app)


def parse_sse(response) -> list[tuple[str, dict]]:
    """Parse a `text/event-stream` response body into (event, data) pairs."""
    events = []
    event_name = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line.removeprefix("data: "))))
    return events


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


def make_ticker(info=None, news=None, history=None):
    ticker = MagicMock()
    ticker.info = info or {}
    ticker.news = news or []
    ticker.history.return_value = history if history is not None else pd.DataFrame()
    return ticker


def full_info(**overrides):
    info = {
        "longName": "NVIDIA Corporation",
        "currentPrice": 132.45,
        "marketCap": 4.78e12,
        "trailingPE": 30.3,
        "regularMarketChangePercent": 1.8,
        "regularMarketChange": 2.34,
    }
    info.update(overrides)
    return info


def default_history():
    return pd.DataFrame(
        {
            "Close": [128.1, 129.4, 132.45],
            "High": [129.0, 130.0, 133.0],
            "Low": [127.0, 128.0, 131.0],
        }
    )


@patch("core.tools.yf.Ticker")
def test_get_watchlist_returns_a_quote_per_default_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info=full_info(), history=default_history())

    response = client.get("/watchlist")

    assert response.status_code == 200
    quotes = response.json()
    assert [q["ticker"] for q in quotes] == api.DEFAULT_WATCHLIST
    assert quotes[0] == {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "price": 132.45,
        "day_change_percent": 1.8,
        "day_change_abs": 2.34,
        "sparkline": [128.1, 129.4, 132.45],
    }


@patch("core.tools.yf.Ticker")
def test_get_ticker_history_returns_prices_for_period(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=default_history())

    response = client.get("/tickers/nvda/history?period=6mo")

    assert response.status_code == 200
    assert response.json() == {"period": "6mo", "prices": [128.1, 129.4, 132.45]}
    mock_ticker_cls.return_value.history.assert_called_with(period="6mo")


@patch("core.tools.yf.Ticker")
def test_get_ticker_history_returns_404_for_unknown_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame())

    response = client.get("/tickers/badticker/history")

    assert response.status_code == 404


@patch("core.tools.yf.Ticker")
def test_get_ticker_snapshot_streams_quote_then_sentiment(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(),
        history=default_history(),
        news=[{"content": {"title": "Nvidia beats estimates"}}],
    )
    test_model = TestModel(custom_output_args={"sentiment": "bullish", "summary": "Strong quarter."})

    with main.sentiment_agent.override(model=test_model):
        response = client.get("/tickers/nvda")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response)

    event_names = [name for name, _ in events]
    assert event_names[0] == "quote"
    assert "tool_call" not in event_names  # sentiment_agent has no tools - headlines are passed in the prompt
    assert event_names[-1] == "sentiment"

    quote = events[0][1]
    assert quote == {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "price": 132.45,
        "market_cap": 4.78e12,
        "pe_ratio": 30.3,
        "day_change_percent": 1.8,
        "day_change_abs": 2.34,
        "news_headlines": ["Nvidia beats estimates"],
    }

    sentiment = events[-1][1]
    assert sentiment == {"sentiment": "bullish", "summary": "Strong quarter."}


@patch("core.tools.yf.Ticker")
def test_get_ticker_snapshot_uppercases_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info=full_info(), history=default_history())
    test_model = TestModel(custom_output_text="x")

    with main.sentiment_agent.override(model=test_model):
        client.get("/tickers/nvda")

    mock_ticker_cls.assert_called_with("NVDA")


@patch("core.tools.yf.Ticker")
def test_get_ticker_snapshot_streams_error_for_unknown_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    response = client.get("/tickers/badticker")

    events = parse_sse(response)
    assert events[-1][0] == "error"
    assert "No" in events[-1][1]["detail"]


@patch("core.tools.yf.Ticker")
def test_get_ticker_team_analysis_streams_tool_events_and_verdict(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(), news=[{"content": {"title": "Nvidia beats estimates"}}]
    )
    synthesizer_model = TestModel(
        custom_output_args={"ticker": "NVDA", "verdict": "buy", "reasoning": "Strong fundamentals."}
    )
    fundamentals_model = TestModel(custom_output_text="Fundamentals summary.")
    sentiment_model = TestModel(custom_output_text="Sentiment summary.")

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
    ):
        response = client.get("/tickers/nvda/team")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response)

    event_names = [name for name, _ in events]
    assert "tool_call" in event_names
    assert "tool_result" in event_names
    assert event_names[-1] == "verdict"

    verdict = events[-1][1]
    assert verdict == {"ticker": "NVDA", "verdict": "buy", "reasoning": "Strong fundamentals."}


@patch("core.tools.yf.Ticker")
def test_get_ticker_team_analysis_streams_error_for_unknown_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={}, news=[])
    synthesizer_model = TestModel(custom_output_args={"ticker": "BAD", "verdict": "hold", "reasoning": "n/a"})
    fundamentals_model = TestModel(custom_output_text="x")
    sentiment_model = TestModel(custom_output_text="x")

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
    ):
        response = client.get("/tickers/badticker/team")

    events = parse_sse(response)
    assert events[-1][0] == "error"
    assert "No" in events[-1][1]["detail"]


@pytest.fixture(autouse=True)
def clear_chat_sessions():
    chat._sessions.clear()
    yield
    chat._sessions.clear()


@patch("core.tools.yf.Ticker")
def test_post_chat_streams_session_then_text_deltas(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(), news=[{"content": {"title": "headline"}}], history=default_history()
    )
    test_model = TestModel(custom_output_text="NVDA is at $132.45.")

    with chat.agent.override(model=test_model):
        response = client.post("/chat", json={"message": "What's NVDA's price?"})

    assert response.status_code == 200
    events = parse_sse(response)

    assert events[0][0] == "session"
    session_id = events[0][1]["session_id"]
    assert session_id

    reply = "".join(data["delta"] for name, data in events if name == "text")
    assert reply == "NVDA is at $132.45."


@patch("core.tools.yf.Ticker")
def test_post_chat_reuses_provided_session_id(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(), news=[{"content": {"title": "headline"}}], history=default_history()
    )
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model):
        response = client.post("/chat", json={"message": "hi", "session_id": "my-session"})

    events = parse_sse(response)
    assert events[0] == ("session", {"session_id": "my-session"})
    assert "my-session" in chat._sessions
