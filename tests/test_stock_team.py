"""Tests for stock_team.py. Overrides all three agents' models with
TestModel so nothing hits the real Bedrock API, and mocks yf.Ticker so the
specialists' tools don't hit the network - see lessons/10_testing_agents.py.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents import stock_team
from core import tools
from core.db import Base
from core.models import TeamVerdict
from core.models_db import TeamVerdictRecord, User
from core.portfolio_context import PortfolioContext
from core.track_record import log_verdict


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


@pytest.fixture(autouse=True)
def clear_info_cache():
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


_ONE_YEAR_HISTORY = pd.DataFrame(
    {"Close": [100.0, 110.0], "High": [105.0, 112.0], "Low": [98.0, 108.0]},
    index=pd.to_datetime(["2024-01-01", "2025-01-01"]),
)


_FINDING_ARGS = {
    "signal": "positive",
    "headline": "Looks solid on this dimension.",
    "key_points": ["Concrete figure one.", "Concrete figure two."],
}


@pytest.mark.asyncio
async def test_get_team_analysis_returns_verdict():
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "buy",
            "key_factors": ["Fundamentals: strong.", "Sentiment: bullish."],
            "reasoning": "Strong fundamentals and bullish sentiment.",
            "predicted_price": 145.0,
            "predicted_horizon": "1mo",
        }
    )
    fundamentals_model = TestModel(custom_output_args=_FINDING_ARGS)
    sentiment_model = TestModel(custom_output_args=_FINDING_ARGS)
    technicals_model = TestModel(custom_output_args=_FINDING_ARGS)
    valuation_model = TestModel(custom_output_args=_FINDING_ARGS)
    risk_model = TestModel(custom_output_args=_FINDING_ARGS)

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        stock_team.technicals_agent.override(model=technicals_model),
        stock_team.valuation_agent.override(model=valuation_model),
        stock_team.risk_agent.override(model=risk_model),
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        mock_ticker_cls.return_value.info = {
            "currentPrice": 132.45,
            "marketCap": 4.78e12,
            "trailingPE": 30.3,
            "beta": 1.05,
            "sector": "Technology",
            "industry": "Semiconductors",
            "regularMarketChangePercent": 1.2,
            "regularMarketChange": 1.6,
            "hasPrePostMarketData": False,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Nvidia beats estimates"}}]
        mock_ticker_cls.return_value.history.return_value = _ONE_YEAR_HISTORY

        analysis = await stock_team.get_team_analysis("NVDA")

    assert analysis.verdict.ticker == "NVDA"
    assert analysis.verdict.verdict == "buy"
    assert analysis.verdict.reasoning == "Strong fundamentals and bullish sentiment."
    assert analysis.is_held is None


@pytest.mark.asyncio
async def test_get_team_analysis_delegates_to_all_specialists():
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "AAPL",
            "verdict": "hold",
            "key_factors": ["Mixed signals across specialists."],
            "reasoning": "Mixed signals.",
            "predicted_price": 255.0,
            "predicted_horizon": "1mo",
        }
    )
    fundamentals_model = TestModel(custom_output_args=_FINDING_ARGS)
    sentiment_model = TestModel(custom_output_args=_FINDING_ARGS)
    technicals_model = TestModel(custom_output_args=_FINDING_ARGS)
    valuation_model = TestModel(custom_output_args=_FINDING_ARGS)
    risk_model = TestModel(custom_output_args=_FINDING_ARGS)

    with (
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=fundamentals_model),
        stock_team.sentiment_agent.override(model=sentiment_model),
        stock_team.technicals_agent.override(model=technicals_model),
        stock_team.valuation_agent.override(model=valuation_model),
        stock_team.risk_agent.override(model=risk_model),
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        mock_ticker_cls.return_value.info = {
            "currentPrice": 250.0,
            "marketCap": 3.8e12,
            "trailingPE": 35.0,
            "beta": 1.2,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "regularMarketChangePercent": -0.5,
            "regularMarketChange": -1.25,
            "hasPrePostMarketData": False,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Apple headline"}}]
        mock_ticker_cls.return_value.history.return_value = _ONE_YEAR_HISTORY

        analysis = await stock_team.get_team_analysis("AAPL")

    assert analysis.verdict.ticker == "AAPL"
    assert analysis.verdict.verdict == "hold"
    assert {c["specialist_key"] for c in analysis.specialist_calls} == {
        "get_fundamentals",
        "get_sentiment",
        "get_technicals",
        "get_valuation",
        "get_risk",
    }
    assert all(c["signal"] == "positive" for c in analysis.specialist_calls)


@pytest.mark.asyncio
async def test_get_portfolio_fit_falls_back_when_no_brokerage_connected():
    """No LLM override needed - ctx.deps.portfolio_summary is None (the
    default), so the tool short-circuits before calling portfolio_fit_agent."""
    deps = stock_team.TeamDeps(portfolio_summary=None)
    ctx = SimpleNamespace(deps=deps, usage=None)

    result = await stock_team.get_portfolio_fit(ctx, "NVDA")

    assert result["signal"] == "neutral"
    assert "No brokerage connected" in result["headline"]


@pytest.mark.asyncio
async def test_get_portfolio_fit_consults_specialist_when_portfolio_available():
    portfolio_fit_model = TestModel(
        custom_output_args={
            "signal": "negative",
            "headline": "Adds to an already concentrated Technology position.",
            "key_points": ["Technology is 80% of the portfolio.", "NVDA is not currently held."],
        }
    )

    with stock_team.portfolio_fit_agent.override(model=portfolio_fit_model):
        deps = stock_team.TeamDeps(portfolio_summary="Portfolio total value: $10,000\nSector weights:\n- Technology: 80.0%")
        ctx = SimpleNamespace(deps=deps, usage=None)

        result = await stock_team.get_portfolio_fit(ctx, "NVDA")

    assert result["signal"] == "negative"
    assert "concentrated" in result["headline"]


def _team_analysis_context_managers(synthesizer_model, portfolio_fit_model=None):
    return [
        stock_team.synthesizer.override(model=synthesizer_model),
        stock_team.fundamentals_agent.override(model=TestModel(custom_output_args=_FINDING_ARGS)),
        stock_team.sentiment_agent.override(model=TestModel(custom_output_args=_FINDING_ARGS)),
        stock_team.technicals_agent.override(model=TestModel(custom_output_args=_FINDING_ARGS)),
        stock_team.valuation_agent.override(model=TestModel(custom_output_args=_FINDING_ARGS)),
        stock_team.risk_agent.override(model=TestModel(custom_output_args=_FINDING_ARGS)),
        stock_team.portfolio_fit_agent.override(model=portfolio_fit_model or TestModel(custom_output_args=_FINDING_ARGS)),
    ]


@pytest.mark.asyncio
async def test_get_team_analysis_uses_portfolio_context_when_db_and_user_given():
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "hold",
            "key_factors": ["Portfolio fit: adds concentration."],
            "reasoning": "Concentration risk offsets otherwise solid fundamentals.",
            "predicted_price": 140.0,
            "predicted_horizon": "3mo",
        }
    )
    portfolio_context = PortfolioContext(summary="Portfolio total value: $10,000", is_held=True)

    with (
        ExitStack() as stack,
        patch("agents.stock_team.build_portfolio_context", return_value=portfolio_context) as mock_build,
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        for ctx in _team_analysis_context_managers(synthesizer_model):
            stack.enter_context(ctx)
        mock_ticker_cls.return_value.info = {
            "currentPrice": 132.45,
            "marketCap": 4.78e12,
            "trailingPE": 30.3,
            "beta": 1.05,
            "sector": "Technology",
            "industry": "Semiconductors",
            "regularMarketChangePercent": 1.2,
            "regularMarketChange": 1.6,
            "hasPrePostMarketData": False,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Nvidia beats estimates"}}]
        mock_ticker_cls.return_value.history.return_value = _ONE_YEAR_HISTORY

        analysis = await stock_team.get_team_analysis("NVDA", db=object(), user_id=1)

    mock_build.assert_called_once_with(mock_build.call_args.args[0], 1, "NVDA")
    assert analysis.verdict.verdict == "hold"
    assert analysis.is_held is True


@pytest.mark.asyncio
async def test_get_team_analysis_clamps_sell_to_hold_when_not_held():
    """The synthesizer shouldn't recommend selling shares the user doesn't
    own - even if it ignores the prompt instruction, the defensive clamp in
    get_team_analysis should still catch it."""
    synthesizer_model = TestModel(
        custom_output_args={
            "ticker": "NVDA",
            "verdict": "sell",
            "key_factors": ["Risk: elevated volatility."],
            "reasoning": "Looks risky.",
            "predicted_price": 120.0,
            "predicted_horizon": "1w",
        }
    )
    portfolio_context = PortfolioContext(summary="not held", is_held=False)

    with (
        ExitStack() as stack,
        patch("agents.stock_team.build_portfolio_context", return_value=portfolio_context),
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        for ctx in _team_analysis_context_managers(synthesizer_model):
            stack.enter_context(ctx)
        mock_ticker_cls.return_value.info = {
            "currentPrice": 132.45,
            "marketCap": 4.78e12,
            "trailingPE": 30.3,
            "beta": 1.05,
            "sector": "Technology",
            "industry": "Semiconductors",
            "regularMarketChangePercent": 1.2,
            "regularMarketChange": 1.6,
            "hasPrePostMarketData": False,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Nvidia beats estimates"}}]
        mock_ticker_cls.return_value.history.return_value = _ONE_YEAR_HISTORY

        analysis = await stock_team.get_team_analysis("NVDA", db=object(), user_id=1)

    assert analysis.verdict.verdict == "hold"
    assert analysis.is_held is False


def test_ownership_instruction_variants():
    assert "isn't connected" in stock_team._ownership_instruction("NVDA", None)
    assert "Choose 'buy'" in stock_team._ownership_instruction("NVDA", True)
    assert "never 'sell'" in stock_team._ownership_instruction("NVDA", False)


@pytest.mark.asyncio
async def test_run_team_scan_reuses_todays_verdict_and_runs_new_tickers(db):
    session, user_id = db
    log_verdict(
        session,
        user_id,
        "AAPL",
        250.0,
        TeamVerdict(
            ticker="AAPL",
            verdict="sell",
            key_factors=["Already called today."],
            reasoning="Already called today.",
            predicted_price=200.0,
            predicted_horizon="1mo",
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

    with (
        ExitStack() as stack,
        patch("core.tools.yf.Ticker") as mock_ticker_cls,
    ):
        for ctx in _team_analysis_context_managers(synthesizer_model):
            stack.enter_context(ctx)
        mock_ticker_cls.return_value.info = {
            "currentPrice": 132.45,
            "marketCap": 4.78e12,
            "trailingPE": 30.3,
            "beta": 1.05,
            "sector": "Technology",
            "industry": "Semiconductors",
            "regularMarketChangePercent": 1.2,
            "regularMarketChange": 1.6,
            "hasPrePostMarketData": False,
        }
        mock_ticker_cls.return_value.news = [{"content": {"title": "Nvidia beats estimates"}}]
        mock_ticker_cls.return_value.history.return_value = _ONE_YEAR_HISTORY

        results = [r async for r in stock_team.run_team_scan(["AAPL", "NVDA"], session, user_id)]

    assert results[0] == {
        "ticker": "AAPL",
        "verdict": "sell",
        "predicted_price": 200.0,
        "predicted_horizon": "1mo",
        "reused": True,
    }
    assert results[1]["ticker"] == "NVDA"
    assert results[1]["verdict"] == "buy"
    assert results[1]["reused"] is False

    logged_nvda = session.execute(select(TeamVerdictRecord).where(TeamVerdictRecord.ticker == "NVDA")).scalars().all()
    assert len(logged_nvda) == 1
    assert logged_nvda[0].verdict == "buy"
