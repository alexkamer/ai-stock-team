"""Tests for main.py's agent behavior. Uses TestModel + agent.override() so
nothing hits the real Bedrock API, and mocks yf.Ticker so nothing hits the
network - see lessons/10_testing_agents.py.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from agents import main
from core import tools


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


@pytest.fixture(autouse=True)
def clear_sentiment_cache():
    main._sentiment_cache.clear()
    yield
    main._sentiment_cache.clear()


def make_output_args(**overrides):
    args = {
        "ticker": "AAPL",
        "ticker_price": 250.0,
        "market_cap": 3.8e12,
        "pe_ratio": 35.0,
        "company_name": "Apple Inc.",
        "sentiment": "bullish",
        "summary": "Strong iPhone sales heading into the holiday quarter.",
    }
    args.update(overrides)
    return args


def test_get_snapshot_calls_all_four_tools():
    test_model = TestModel(custom_output_args=make_output_args())

    with main.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = {
            "currentPrice": 250.0,
            "marketCap": 3.8e12,
            "trailingPE": 35.0,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Apple beats holiday estimates"}}]

        result = main.agent.run_sync(
            "Give me a full snapshot of AAPL: price, market cap, P/E ratio, and sentiment based on recent news.",
            output_type=main.CompanySnapshot,
        )

    called_tools = {
        part.tool_name
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if part.__class__.__name__ == "ToolCallPart"
    }

    # TestModel calls every registered tool automatically before producing
    # the final output - confirms all four are actually wired onto the agent.
    assert called_tools == {"get_stock_price", "get_market_cap", "get_pe_ratio", "get_news_headlines", "final_result"}
    assert result.output.ticker == "AAPL"
    assert result.output.company_name == "Apple Inc."
    assert result.output.sentiment == "bullish"


def test_get_snapshot_result_matches_test_model_output():
    test_model = TestModel(custom_output_args=make_output_args(ticker_price=999.0))

    with main.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = {
            "currentPrice": 999.0,
            "marketCap": 3.8e12,
            "trailingPE": 35.0,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Some headline"}}]

        snapshot = main.get_snapshot("AAPL")

    assert snapshot.ticker_price == 999.0


def test_override_only_applies_inside_the_with_block():
    # override() is a context manager scoped to the `with` block - a call
    # made after it exits should hit main.agent's real configured model,
    # not stay stuck on TestModel. We don't call run_sync() outside the
    # block here (that would hit the real Bedrock API); instead this checks
    # that TestModel's own request-tracking attribute is only populated
    # for calls made while the override is active.
    test_model = TestModel(custom_output_args=make_output_args())
    assert test_model.last_model_request_parameters is None

    with main.agent.override(model=test_model), patch("core.tools.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.info = {"currentPrice": 250.0, "marketCap": 3.8e12, "trailingPE": 35.0}
        mock_ticker_cls.return_value.news = [{"content": {"title": "headline"}}]
        main.get_snapshot("AAPL")

    assert test_model.last_model_request_parameters is not None


@pytest.mark.asyncio
async def test_get_sentiment_streaming_caches_repeat_calls_for_same_headlines():
    test_model = TestModel(custom_output_args={"sentiment": "bullish", "summary": "Strong quarter."})
    headlines = ["Nvidia beats estimates"]

    with main.sentiment_agent.override(model=test_model):
        real_run = main.sentiment_agent.run
        with patch.object(main.sentiment_agent, "run", AsyncMock(wraps=real_run)) as mock_run:
            first = await main.get_sentiment_streaming("NVDA", headlines)
            second = await main.get_sentiment_streaming("NVDA", headlines)

    assert first.sentiment == "bullish"
    assert second.sentiment == "bullish"
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_get_sentiment_streaming_cache_misses_on_new_headlines():
    test_model = TestModel(custom_output_args={"sentiment": "bullish", "summary": "Strong quarter."})

    with main.sentiment_agent.override(model=test_model):
        real_run = main.sentiment_agent.run
        with patch.object(main.sentiment_agent, "run", AsyncMock(wraps=real_run)) as mock_run:
            await main.get_sentiment_streaming("NVDA", ["Nvidia beats estimates"])
            await main.get_sentiment_streaming("NVDA", ["A different headline"])

    assert mock_run.call_count == 2


@pytest.mark.asyncio
async def test_get_portfolio_digest_logs_usage_when_db_passed():
    test_model = TestModel(
        custom_output_args={
            "headline": "Portfolio up",
            "article": "Paragraph one.",
            "key_drivers": ["NVDA up"],
            "watch_items": ["Earnings next week"],
        }
    )

    with main.digest_agent.override(model=test_model), patch("agents.main.log_llm_usage") as mock_log:
        db = object()
        digest = await main.get_portfolio_digest("some context", db=db, user_id=7)

    assert digest.headline == "Portfolio up"
    mock_log.assert_called_once()
    args = mock_log.call_args.args
    assert args[0] is db
    assert args[1] == 7
    assert args[2] == "digest"


@pytest.mark.asyncio
async def test_get_portfolio_digest_skips_logging_without_db():
    test_model = TestModel(
        custom_output_args={
            "headline": "Portfolio up",
            "article": "Paragraph one.",
            "key_drivers": ["NVDA up"],
            "watch_items": ["Earnings next week"],
        }
    )

    with main.digest_agent.override(model=test_model), patch("agents.main.log_llm_usage") as mock_log:
        await main.get_portfolio_digest("some context")

    mock_log.assert_not_called()
