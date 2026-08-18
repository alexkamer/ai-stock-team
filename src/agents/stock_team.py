"""Stock Team multi-agent analysis (Lesson 09) wired for the API.

Six narrow specialists (fundamentals, sentiment, technicals, valuation vs.
peers, risk/macro, portfolio fit) plus a synthesizer that delegates to all of
them and renders a buy/hold/sell verdict. Mirrors
lessons/09_multi_agent_composition.py, but with structured
`SpecialistFinding`/`TeamVerdict` output (signal + short headline + bullet
points) instead of free text, so the frontend can render scannable cards
instead of a wall of prose.
"""

import asyncio
from dataclasses import dataclass

from pydantic_ai import RunContext

from core.config import load_agent
from core.models import SpecialistFinding, TeamVerdict
from core.portfolio_context import build_portfolio_context
from core.tools import (
    get_market_cap,
    get_news_headlines,
    get_pe_ratio,
    get_price_performance,
    get_price_ratios,
    get_similar_tickers,
    get_stock_price,
    get_technical_indicators,
    get_ticker_overview,
    get_ticker_stats,
)


@dataclass
class TeamDeps:
    """Per-run context the synthesizer's tools can read via RunContext.deps -
    the user's portfolio summary text plus whether they actually hold the
    ticker (None for both if no brokerage is connected, since ownership is
    genuinely unknown then). Assembled per-call from the DB/SnapTrade rather
    than being a static tool any agent can call on its own."""

    portfolio_summary: str | None = None
    is_held: bool | None = None


fundamentals_agent = load_agent(tools=[get_stock_price, get_market_cap, get_pe_ratio])
sentiment_agent = load_agent(tools=[get_news_headlines])
technicals_agent = load_agent(tools=[get_technical_indicators, get_price_performance, get_ticker_stats])
valuation_agent = load_agent(tools=[get_ticker_overview, get_price_ratios, get_similar_tickers])
risk_agent = load_agent(tools=[get_technical_indicators, get_ticker_stats, get_price_performance])
portfolio_fit_agent = load_agent()
synthesizer = load_agent(deps_type=TeamDeps)


@synthesizer.tool
async def get_fundamentals(ctx: RunContext, ticker: str) -> dict:
    """Ask the fundamentals specialist for a ticker's price, market cap, and P/E ratio.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await fundamentals_agent.run(
        f"Look up {ticker}'s current price, market cap, and P/E ratio, then judge whether that profile "
        "looks positive, neutral, or negative for the stock.",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@synthesizer.tool
async def get_sentiment(ctx: RunContext, ticker: str) -> dict:
    """Ask the sentiment specialist to judge market mood from recent news on a ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await sentiment_agent.run(
        f"Based on recent headlines, judge whether sentiment on {ticker} is positive, neutral, or "
        "negative.",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@synthesizer.tool
async def get_technicals(ctx: RunContext, ticker: str) -> dict:
    """Ask the technicals specialist to judge momentum/trend from recent price action.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await technicals_agent.run(
        f"Look up {ticker}'s computed technical indicators (20/50/200-day moving averages, RSI-14, "
        "MACD) and trailing price performance/52-week range, then judge whether current momentum/trend "
        "is positive, neutral, or negative. Cite the actual indicator values and crossovers (e.g. price "
        "above/below its moving averages, RSI overbought/oversold, MACD bullish/bearish crossover), not "
        "just the raw percent-change numbers.",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@synthesizer.tool
async def get_valuation(ctx: RunContext, ticker: str) -> dict:
    """Ask the valuation specialist how a ticker's multiples compare to its peers.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await valuation_agent.run(
        f"Look up {ticker}'s valuation (P/E, EV/EBITDA, price-to-sales, etc.) and its industry/sector "
        "peers, then judge whether it looks cheap (positive), fairly valued (neutral), or expensive "
        "(negative) relative to those peers.",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@synthesizer.tool
async def get_risk(ctx: RunContext, ticker: str) -> dict:
    """Ask the risk/macro specialist to assess volatility and downside risk for a ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await risk_agent.run(
        f"Look up {ticker}'s beta, computed 30-day annualized realized volatility, and trailing price "
        "performance, then judge its volatility/downside risk as low (positive), moderate (neutral), or "
        "high (negative). Cite the actual computed volatility figure, not just beta.",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@synthesizer.tool
async def get_portfolio_fit(ctx: RunContext[TeamDeps], ticker: str) -> dict:
    """Ask the portfolio fit specialist how this ticker fits the user's actual brokerage holdings.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    if ctx.deps.portfolio_summary is None:
        return {
            "signal": "neutral",
            "headline": "No brokerage connected - portfolio fit unavailable.",
            "key_points": ["Connect a brokerage on the Brokerage page for concentration-aware sizing advice."],
        }
    result = await portfolio_fit_agent.run(
        f"Given this portfolio, judge how holding/adding {ticker} affects concentration and "
        "diversification: positive (reasonable size, adds diversification), neutral, or negative (adds "
        "unwanted concentration risk). Cite the actual weights from the summary below.\n\n"
        f"{ctx.deps.portfolio_summary}",
        usage=ctx.usage,
        output_type=SpecialistFinding,
    )
    return result.output.model_dump()


@dataclass
class TeamAnalysisResult:
    """get_team_analysis's return value - the verdict plus whether the user
    actually holds the ticker (None if ownership is unknown), so the API
    layer can surface that alongside the verdict without recomputing
    portfolio context a second time."""

    verdict: TeamVerdict
    is_held: bool | None


def _ownership_instruction(ticker: str, is_held: bool | None) -> str:
    if is_held is None:
        return (
            f"The user's brokerage isn't connected, so ownership of {ticker} is unknown - weigh "
            "buy/hold/sell purely on the specialists' findings."
        )
    if is_held:
        return (
            f"The user currently holds {ticker}. Choose 'buy' (add to the position), 'hold' (keep the "
            "position as-is), or 'sell' (exit or trim it) based on the specialists' findings."
        )
    return (
        f"The user does NOT currently hold {ticker} - they can't sell shares they don't own, so your "
        "verdict must be 'buy' or 'hold', never 'sell'. Here 'hold' means this isn't compelling enough "
        "to buy right now, not an instruction to keep an existing position (there isn't one)."
    )


async def get_team_analysis(
    ticker: str, event_stream_handler=None, db=None, user_id: int | None = None
) -> TeamAnalysisResult:
    portfolio_context = (
        await asyncio.to_thread(build_portfolio_context, db, user_id, ticker)
        if db is not None and user_id is not None
        else None
    )
    is_held = portfolio_context.is_held if portfolio_context else None

    result = await synthesizer.run(
        f"Give me a buy/hold/sell take on {ticker}, weighing fundamentals, sentiment, technicals, "
        "valuation relative to peers, risk/macro considerations, and how it fits the user's actual "
        f"portfolio. {_ownership_instruction(ticker, is_held)} Also give a specific predicted_price "
        "target and pick the predicted_horizon (1w/1mo/3mo) it applies to, consistent with your verdict "
        "and the specialists' findings (e.g. a buy should target a price above the current one).",
        output_type=TeamVerdict,
        event_stream_handler=event_stream_handler,
        deps=TeamDeps(
            portfolio_summary=portfolio_context.summary if portfolio_context else None,
            is_held=is_held,
        ),
    )
    verdict = result.output
    if is_held is False and verdict.verdict == "sell":
        # Defensive clamp - the model shouldn't recommend selling shares that
        # don't exist, even though the prompt above already tells it not to.
        verdict.verdict = "hold"
    return TeamAnalysisResult(verdict=verdict, is_held=is_held)
