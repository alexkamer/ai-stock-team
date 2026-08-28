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
from dataclasses import dataclass, field

from pydantic_ai import RunContext
from pydantic_ai.usage import RunUsage

from core.config import load_agent
from core.grounding import check_findings_are_grounded
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
from core.track_record import get_todays_verdict, log_verdict


@dataclass
class TeamDeps:
    """Per-run context the synthesizer's tools can read via RunContext.deps -
    the user's portfolio summary text plus whether they actually hold the
    ticker (None for both if no brokerage is connected, since ownership is
    genuinely unknown then). Assembled per-call from the DB/SnapTrade rather
    than being a static tool any agent can call on its own."""

    portfolio_summary: str | None = None
    is_held: bool | None = None
    # Populated by each specialist tool below as it returns, so
    # get_team_analysis can hand the signals to the caller for track-record
    # persistence - the synthesizer LLM only ever sees the dict it returns,
    # not this list.
    specialist_calls: list[dict] = field(default_factory=list)


# retries=3 (vs. config.yaml's default of 1): for the specialists, gives
# check_findings_are_grounded room for a borderline false positive (a
# legitimately-derived stat it doesn't recognize); for the synthesizer
# (below), covers an occasional schema-invalid TeamVerdict on the first try.
# Either way, the default of 1 leaves no room for a single hiccup before
# hard-failing the whole run.
_AGENT_RETRIES = 3

fundamentals_agent = load_agent(
    tools=[get_stock_price, get_market_cap, get_pe_ratio], output_type=SpecialistFinding, retries=_AGENT_RETRIES
)
sentiment_agent = load_agent(
    tools=[get_news_headlines], output_type=SpecialistFinding, retries=_AGENT_RETRIES
)
technicals_agent = load_agent(
    tools=[get_technical_indicators, get_price_performance, get_ticker_stats],
    output_type=SpecialistFinding,
    retries=_AGENT_RETRIES,
)
valuation_agent = load_agent(
    tools=[get_ticker_overview, get_price_ratios, get_similar_tickers],
    output_type=SpecialistFinding,
    retries=_AGENT_RETRIES,
)
risk_agent = load_agent(
    tools=[get_technical_indicators, get_ticker_stats, get_price_performance],
    output_type=SpecialistFinding,
    retries=_AGENT_RETRIES,
)
portfolio_fit_agent = load_agent()
# Same retries budget as the specialists above, but for a different reason:
# this agent has no output_validator, so a retry here only ever covers the
# model failing to produce a schema-valid TeamVerdict on the first try (e.g.
# a predicted_price inconsistent with the verdict direction) - without it,
# any single validation hiccup fails the whole run with no second chance.
synthesizer = load_agent(deps_type=TeamDeps, retries=_AGENT_RETRIES)

# Every tool-using specialist gets the same numeric-grounding check (a no-op
# for sentiment_agent, whose tool returns headline text with no numbers to
# cite) - portfolio_fit_agent has no tools of its own to be grounded against.
# Their output_type is fixed at construction above (not passed to .run())
# because pydantic-ai forbids a per-run output_type once a validator is
# attached.
for _specialist in (fundamentals_agent, sentiment_agent, technicals_agent, valuation_agent, risk_agent):
    _specialist.output_validator(check_findings_are_grounded)


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
    )
    ctx.deps.specialist_calls.append({"specialist_key": "get_fundamentals", "signal": result.output.signal})
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
    )
    ctx.deps.specialist_calls.append({"specialist_key": "get_sentiment", "signal": result.output.signal})
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
    )
    ctx.deps.specialist_calls.append({"specialist_key": "get_technicals", "signal": result.output.signal})
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
    )
    ctx.deps.specialist_calls.append({"specialist_key": "get_valuation", "signal": result.output.signal})
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
    )
    ctx.deps.specialist_calls.append({"specialist_key": "get_risk", "signal": result.output.signal})
    return result.output.model_dump()


@synthesizer.tool
async def get_portfolio_fit(ctx: RunContext[TeamDeps], ticker: str) -> dict:
    """Ask the portfolio fit specialist how this ticker fits the user's actual brokerage holdings.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    if ctx.deps.portfolio_summary is None:
        # Not recorded in specialist_calls - this is a canned fallback with
        # no real judgment behind it, not an analysis worth scoring for
        # accuracy.
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
    ctx.deps.specialist_calls.append({"specialist_key": "get_portfolio_fit", "signal": result.output.signal})
    return result.output.model_dump()


@dataclass
class TeamAnalysisResult:
    """get_team_analysis's return value - the verdict plus whether the user
    actually holds the ticker (None if ownership is unknown), so the API
    layer can surface that alongside the verdict without recomputing
    portfolio context a second time."""

    verdict: TeamVerdict
    is_held: bool | None
    usage: RunUsage
    specialist_calls: list[dict]


_SYNTHESIS_RUBRIC = """\
1. Match specialists to the horizon you're targeting, don't average all six evenly:
   - 1w calls: weight technicals and risk/macro most heavily (they capture near-term momentum and
     volatility). Sentiment is a secondary confirming/disconfirming signal here, not a primary driver.
   - 1mo calls: weight technicals, sentiment, and risk roughly evenly; valuation/fundamentals matter less
     since multiples rarely re-rate that fast.
   - 3mo calls: weight fundamentals and valuation most heavily (multiples and earnings trajectory play
     out over quarters); a short-term technical pullback matters less at this horizon.
2. When specialists disagree, don't silently average into a default 'hold'. Name the conflict explicitly
   in reasoning (e.g. "technicals are bullish but valuation and risk are both negative"), say which
   side you weighted more heavily for the horizon you picked, and say why.
3. Each key_factors bullet must state the specialist's finding AND its implication for the verdict, not
   just restate the specialist's headline verbatim - e.g. not "Valuation: expensive vs peers" but
   "Valuation: 120x P/E vs peers' 20-60x leaves little room for a miss, arguing against adding here."
4. portfolio_fit changes sizing/timing (e.g. tempers a buy into a hold if already overweight), not
   direction - don't let it override a clear fundamentals/technicals/valuation signal on its own.\
"""


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

    deps = TeamDeps(
        portfolio_summary=portfolio_context.summary if portfolio_context else None,
        is_held=is_held,
    )
    result = await synthesizer.run(
        f"Give me a buy/hold/sell take on {ticker}. Call all six specialist tools first, then weigh "
        f"their findings using this rubric before writing key_factors/reasoning:\n\n"
        f"{_SYNTHESIS_RUBRIC}\n\n"
        f"{_ownership_instruction(ticker, is_held)} Also give a specific predicted_price target and pick "
        "the predicted_horizon (1w/1mo/3mo) it applies to, consistent with your verdict and the "
        "specialists' findings (e.g. a buy should target a price above the current one) - and consistent "
        "with which horizon you weighted most heavily per the rubric above.",
        output_type=TeamVerdict,
        event_stream_handler=event_stream_handler,
        deps=deps,
    )
    verdict = result.output
    if is_held is False and verdict.verdict == "sell":
        # Defensive clamp - the model shouldn't recommend selling shares that
        # don't exist, even though the prompt above already tells it not to.
        verdict.verdict = "hold"
    return TeamAnalysisResult(
        verdict=verdict, is_held=is_held, usage=result.usage, specialist_calls=deps.specialist_calls
    )


_SCAN_MAX_CONCURRENCY = 3


async def _run_scan_one(ticker: str, user_id: int, session_factory) -> dict:
    """One ticker's slice of run_team_scan - own db session (not the
    caller's), since several of these can now run concurrently and a
    SQLAlchemy Session isn't safe for concurrent use from multiple tasks."""
    db = session_factory()
    try:
        existing = await asyncio.to_thread(get_todays_verdict, db, user_id, ticker)
        if existing is not None:
            return {
                "ticker": ticker,
                "verdict": existing.verdict,
                "predicted_price": existing.predicted_price,
                "predicted_horizon": existing.predicted_horizon,
                "reused": True,
            }

        analysis = await get_team_analysis(ticker, db=db, user_id=user_id)
        price_at_call = await asyncio.to_thread(get_stock_price, ticker)
        await asyncio.to_thread(
            log_verdict,
            db,
            user_id,
            ticker,
            price_at_call,
            analysis.verdict,
            specialist_calls=analysis.specialist_calls,
        )
        return {
            "ticker": ticker,
            "verdict": analysis.verdict.verdict,
            "predicted_price": analysis.verdict.predicted_price,
            "predicted_horizon": analysis.verdict.predicted_horizon,
            "reused": False,
        }
    except Exception as e:
        # Reported and skipped rather than aborting the rest of the scan -
        # one bad ticker (thin data, a model hiccup) shouldn't sink the run.
        return {"ticker": ticker, "error": str(e)}
    finally:
        db.close()


async def run_team_scan(
    tickers: list[str],
    user_id: int,
    session_factory=None,
    max_concurrency: int = _SCAN_MAX_CONCURRENCY,
):
    """Runs get_team_analysis for up to `max_concurrency` tickers at once
    (each on its own db session - see _run_scan_one), reusing today's
    already-logged verdict when one exists instead of re-running the (6
    specialists + synthesizer) pipeline, so re-scanning the same candidate
    list later the same day is cheap. Yields one result dict per ticker as
    it finishes - not necessarily in `tickers` order, since faster tickers
    (reused, or just quicker to analyze) can complete before slower ones -
    so a caller can stream progress instead of waiting for the whole scan.
    `session_factory` defaults to core.db.SessionLocal; tests override it to
    point at an in-memory engine."""
    if session_factory is None:
        from core.db import SessionLocal  # local import - avoids a hard dependency for callers that override it

        session_factory = SessionLocal

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded(ticker: str) -> dict:
        async with semaphore:
            return await _run_scan_one(ticker, user_id, session_factory)

    for task in asyncio.as_completed([asyncio.create_task(_bounded(t)) for t in tickers]):
        yield await task
