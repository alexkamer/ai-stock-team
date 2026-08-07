"""Tests for stock_team.py. Overrides all three agents' models with
TestModel so nothing hits the real Bedrock API, and mocks yf.Ticker so the
specialists' tools don't hit the network - see lessons/10_testing_agents.py.
"""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from agents import stock_team
from core import tools


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


@pytest.mark.asyncio
async def test_get_team_analysis_returns_verdict():
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "buy",
            "reasoning": "Strong fundamentals and bullish sentiment.",
        }
    )
    fundamentals_model = TestModel(custom_output_text="Price $132.45, market cap $4.78T, P/E 30.3.")
    sentiment_model = TestModel(custom_output_text="Bullish - recent headlines are positive.")

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        mock_ticker_cls.return_value.info = {
            "currentPrice": 132.45,
            "marketCap": 4.78e12,
            "trailingPE": 30.3,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Nvidia beats estimates"}}]

        verdict = await stock_team.get_team_analysis("NVDA")

    assert verdict.ticker == "NVDA"
    assert verdict.verdict == "buy"
    assert verdict.reasoning == "Strong fundamentals and bullish sentiment."


@pytest.mark.asyncio
async def test_get_team_analysis_delegates_to_both_specialists():
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "AAPL",
            "verdict": "hold",
            "reasoning": "Mixed signals.",
        }
    )
    fundamentals_model = TestModel(custom_output_text="Fundamentals summary.")
    sentiment_model = TestModel(custom_output_text="Sentiment summary.")

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        mock_ticker_cls.return_value.info = {
            "currentPrice": 250.0,
            "marketCap": 3.8e12,
            "trailingPE": 35.0,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Apple headline"}}]

        result = await stock_team.get_team_analysis("AAPL")

    assert result.ticker == "AAPL"
    assert result.verdict == "hold"
