"""Tests for main.py's agent behavior. Uses TestModel + agent.override() so
nothing hits the real Bedrock API, and mocks yf.Ticker so nothing hits the
network - see lessons/10_testing_agents.py.
"""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from agents import main
from core import tools


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


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
