"""Tests for api.py. Mocks yf.Ticker so nothing hits the network."""

import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents import chat, main, stock_team
from core import api, tools
from core.db import Base, get_db
from core.models_db import TeamVerdictRecord

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def isolated_db():
    """Team-analysis logging and /track-record touch the DB - route them to
    an in-memory SQLite instance instead of the real local dev DB, same
    approach as test_brokerage.py's isolated_db."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        "day_prices": [128.1, 129.4, 132.45],
    }


@patch("core.tools.yf.Ticker")
def test_get_home_news_returns_merged_articles(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(),
        news=[
            {
                "content": {
                    "title": "Nvidia beats estimates",
                    "canonicalUrl": {"url": "https://example.com/a"},
                    "provider": {"displayName": "Reuters"},
                    "pubDate": "2026-08-07T12:00:00Z",
                }
            }
        ],
    )

    response = client.get("/news")

    assert response.status_code == 200
    articles = response.json()
    assert articles == [
        {
            "title": "Nvidia beats estimates",
            "publisher": "Reuters",
            "url": "https://example.com/a",
            "published_at": "2026-08-07T12:00:00Z",
            "thumbnail": None,
        }
    ]


@patch("core.tools.yf.Ticker")
@patch("core.tools.requests.get")
def test_get_trending_returns_search_trending_tickers(mock_get, mock_ticker_cls):
    mock_get.return_value.json.return_value = {"finance": {"result": [{"quotes": [{"symbol": "NVDA"}]}]}}
    mock_ticker_cls.return_value = make_ticker(
        info={"currentPrice": 219.78, "longName": "NVIDIA Corporation", "regularMarketChangePercent": 0.26},
        history=pd.DataFrame({"Close": [217.0, 219.78]}),
    )

    response = client.get("/trending")

    assert response.status_code == 200
    assert response.json() == [
        {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "price": 219.78,
            "day_change_percent": 0.26,
            "volume": None,
            "day_prices": [217.0, 219.78],
        }
    ]


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_most_active_returns_active_tickers(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {
        "quotes": [
            {
                "symbol": "NVDA",
                "longName": "NVIDIA Corporation",
                "regularMarketPrice": 219.78,
                "regularMarketChangePercent": 0.26,
                "regularMarketVolume": 5_000_000,
            }
        ]
    }
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [217.0, 219.78]}))

    response = client.get("/most-active")

    assert response.status_code == 200
    assert response.json() == [
        {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "price": 219.78,
            "day_change_percent": 0.26,
            "volume": 5_000_000,
            "day_prices": [217.0, 219.78],
        }
    ]


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_gainers_returns_top_gainers(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {
        "quotes": [
            {
                "symbol": "SPCX",
                "longName": "Space Exploration Technologies Corp.",
                "regularMarketPrice": 131.55,
                "regularMarketChangePercent": 14.47,
                "regularMarketVolume": 210_927_255,
            }
        ]
    }
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [120.0, 131.55]}))

    response = client.get("/gainers")

    assert response.status_code == 200
    assert response.json() == [
        {
            "ticker": "SPCX",
            "company_name": "Space Exploration Technologies Corp.",
            "price": 131.55,
            "day_change_percent": 14.47,
            "volume": 210_927_255,
            "day_prices": [120.0, 131.55],
        }
    ]


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_losers_returns_top_losers(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {
        "quotes": [
            {
                "symbol": "XYZ",
                "longName": "XYZ Corp",
                "regularMarketPrice": 12.34,
                "regularMarketChangePercent": -9.87,
                "regularMarketVolume": 8_000_000,
            }
        ]
    }
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [14.0, 12.34]}))

    response = client.get("/losers")

    assert response.status_code == 200
    assert response.json() == [
        {
            "ticker": "XYZ",
            "company_name": "XYZ Corp",
            "price": 12.34,
            "day_change_percent": -9.87,
            "volume": 8_000_000,
            "day_prices": [14.0, 12.34],
        }
    ]


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
        info=full_info(beta=1.05, sector="Technology", industry="Semiconductors", hasPrePostMarketData=False),
        news=[{"content": {"title": "Nvidia beats estimates"}}],
        history=pd.DataFrame(
            {"Close": [100.0, 132.45], "High": [105.0, 133.0], "Low": [98.0, 128.0]},
            index=pd.to_datetime(["2024-01-01", "2025-01-01"]),
        ),
    )
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "buy",
            "key_factors": ["Fundamentals: strong."],
            "reasoning": "Strong fundamentals.",
            "predicted_price": 145.0,
            "predicted_horizon": "1mo",
        }
    )
    finding_args = {
        "signal": "positive",
        "headline": "Looks solid on this dimension.",
        "key_points": ["Concrete figure one.", "Concrete figure two."],
    }
    fundamentals_model = TestModel(custom_output_args=finding_args)
    sentiment_model = TestModel(custom_output_args=finding_args)
    technicals_model = TestModel(custom_output_args=finding_args)
    valuation_model = TestModel(custom_output_args=finding_args)
    risk_model = TestModel(custom_output_args=finding_args)

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        stock_team.technicals_agent.override(model=technicals_model),
        stock_team.valuation_agent.override(model=valuation_model),
        stock_team.risk_agent.override(model=risk_model),
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
    assert verdict == {
        "ticker": "NVDA",
        "verdict": "buy",
        "key_factors": ["Fundamentals: strong."],
        "reasoning": "Strong fundamentals.",
        "predicted_price": 145.0,
        "predicted_horizon": "1mo",
        "is_held": None,
    }


@patch("core.tools.yf.Ticker")
def test_get_ticker_team_analysis_streams_error_for_unknown_ticker(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={}, news=[])
    synthesizer_model = TestModel(
        custom_output_args={"ticker": "BAD", "verdict": "hold", "key_factors": ["n/a"], "reasoning": "n/a"}
    )
    finding_args = {"signal": "neutral", "headline": "x", "key_points": ["x"]}
    fundamentals_model = TestModel(custom_output_args=finding_args)
    sentiment_model = TestModel(custom_output_args=finding_args)
    technicals_model = TestModel(custom_output_args=finding_args)
    valuation_model = TestModel(custom_output_args=finding_args)
    risk_model = TestModel(custom_output_args=finding_args)

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        stock_team.technicals_agent.override(model=technicals_model),
        stock_team.valuation_agent.override(model=valuation_model),
        stock_team.risk_agent.override(model=risk_model),
    ):
        response = client.get("/tickers/badticker/team")

    events = parse_sse(response)
    assert events[-1][0] == "error"
    assert "No" in events[-1][1]["detail"]


def _team_analysis_overrides():
    """The five specialist model overrides + the shared context manager
    every team-analysis test needs - factored out since the logging tests
    below don't care about the analysis content itself."""
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "buy",
            "key_factors": ["Fundamentals: strong."],
            "reasoning": "Strong fundamentals.",
            "predicted_price": 145.0,
            "predicted_horizon": "1mo",
        }
    )
    finding_args = {
        "signal": "positive",
        "headline": "Looks solid on this dimension.",
        "key_points": ["Concrete figure one.", "Concrete figure two."],
    }
    return [
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=TestModel(custom_output_args=finding_args)),
        stock_team.sentiment_agent.override(model=TestModel(custom_output_args=finding_args)),
        stock_team.technicals_agent.override(model=TestModel(custom_output_args=finding_args)),
        stock_team.valuation_agent.override(model=TestModel(custom_output_args=finding_args)),
        stock_team.risk_agent.override(model=TestModel(custom_output_args=finding_args)),
    ]


@patch("core.tools.yf.Ticker")
def test_get_ticker_team_analysis_logs_a_verdict_row(mock_ticker_cls, isolated_db):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(),
        news=[{"content": {"title": "Nvidia beats estimates"}}],
        history=pd.DataFrame({"Close": [100.0, 132.45]}, index=pd.to_datetime(["2024-01-01", "2025-01-01"])),
    )

    with ExitStack() as stack:
        for ctx in _team_analysis_overrides():
            stack.enter_context(ctx)
        client.get("/tickers/nvda/team")

    session = isolated_db()
    rows = session.execute(select(TeamVerdictRecord)).scalars().all()
    session.close()
    assert len(rows) == 1
    assert rows[0].ticker == "NVDA"
    assert rows[0].verdict == "buy"
    assert rows[0].price_at_call == full_info()["currentPrice"]
    assert rows[0].predicted_price == 145.0
    assert rows[0].predicted_horizon == "1mo"


@patch("core.tools.yf.Ticker")
def test_get_ticker_team_analysis_does_not_log_twice_same_day(mock_ticker_cls, isolated_db):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(),
        news=[{"content": {"title": "Nvidia beats estimates"}}],
        history=pd.DataFrame({"Close": [100.0, 132.45]}, index=pd.to_datetime(["2024-01-01", "2025-01-01"])),
    )

    for _ in range(2):
        with ExitStack() as stack:
            for ctx in _team_analysis_overrides():
                stack.enter_context(ctx)
            client.get("/tickers/nvda/team")

    session = isolated_db()
    rows = session.execute(select(TeamVerdictRecord)).scalars().all()
    session.close()
    assert len(rows) == 1


@patch("core.track_record.yf.Ticker")
def test_get_track_record_returns_scored_records_and_stats(mock_ticker_cls, isolated_db):
    session = isolated_db()
    session.add(
        TeamVerdictRecord(
            user_id=1,
            ticker="NVDA",
            verdict="buy",
            key_factors=json.dumps(["Fundamentals: strong."]),
            reasoning="Strong fundamentals.",
            price_at_call=200.0,
            call_date=date.today() - timedelta(days=10),
        )
    )
    session.commit()
    session.close()

    dates = pd.bdate_range(date.today() - timedelta(days=10), periods=20)

    def ticker_side_effect(symbol):
        base = 100.0 if symbol == "SPY" else 200.0
        rate = 0.0005 if symbol == "SPY" else 0.005
        closes = [base * (1 + rate) ** i for i in range(20)]
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame({"Close": closes}, index=dates)
        return mock_ticker

    mock_ticker_cls.side_effect = ticker_side_effect

    response = client.get("/track-record")

    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) == 1
    assert body["records"][0]["ticker"] == "NVDA"
    assert body["records"][0]["current"]["hit"] is True
    assert body["stats"]["total_calls"] == 1


@patch("core.track_record.yf.Ticker")
def test_get_track_record_filters_by_multiple_tickers(mock_ticker_cls, isolated_db):
    session = isolated_db()
    for ticker in ("NVDA", "AAPL", "TSLA"):
        session.add(
            TeamVerdictRecord(
                user_id=1,
                ticker=ticker,
                verdict="hold",
                key_factors=json.dumps(["x"]),
                reasoning="y",
                price_at_call=100.0,
                call_date=date.today() - timedelta(days=5),
            )
        )
    session.commit()
    session.close()

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker

    response = client.get("/track-record?tickers=NVDA,AAPL")

    assert response.status_code == 200
    body = response.json()
    assert {r["ticker"] for r in body["records"]} == {"NVDA", "AAPL"}


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
def test_post_chat_passes_watchlist_through_to_the_agent(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info=full_info(), news=[{"content": {"title": "headline"}}], history=default_history()
    )
    test_model = TestModel(custom_output_text="Some reply.")

    with chat.agent.override(model=test_model):
        response = client.post("/chat", json={"message": "What's on my watchlist?", "watchlist": ["TSLA", "AMD"]})

    assert response.status_code == 200
    queried_tickers = {call.args[0] for call in mock_ticker_cls.call_args_list}
    assert {"TSLA", "AMD"} <= queried_tickers
    assert "NVDA" not in queried_tickers


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
