"""FastAPI app wrapping the existing agent/tools as HTTP endpoints.

Phase 1 (see WEBAPP_ROADMAP.md): `/tickers/{ticker}/team` and `/chat` stream
via SSE (Lesson 13's event_stream_handler, bridged through sse.py) so the
frontend can render tool-call-in-flight pills and text deltas instead of
blocking on the full agent run.
"""

import asyncio
import json
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from agents.chat import send_message
from agents.main import get_article_summary, get_sentiment_streaming
from agents.stock_team import get_team_analysis, run_team_scan
from agents.theme_builder import get_theme_performance, get_theme_suggestion, promote_theme_suggestion
from core.auth import get_current_user
from core.db import get_db
from core.models_db import TeamVerdictRecord, User
from core.routers import auth as auth_router
from core.routers import brokerage as brokerage_router
from core.sse import Final, format_sse, run_agent_streaming
from core.themes import THEME_CATALOG, get_filings_relevance
from core.track_record import aggregate_stats, log_verdict, score_records, specialist_stats
from core.tools import (
    DEFAULT_WATCHLIST,
    NEWS_CATEGORY_TICKERS,
    get_analyst_ratings,
    get_best_historical_performers,
    get_company_name,
    get_day_change,
    get_day_prices,
    get_highest_open_interest_options,
    get_cash_flow_statement,
    get_highest_valuation_private_companies,
    get_income_statement,
    get_market_cap,
    get_market_news,
    get_most_active_options,
    get_most_active_tickers,
    get_news_headlines,
    get_pe_ratio,
    get_price_performance,
    get_price_ratios,
    get_sparkline,
    get_sparkline_prices,
    get_diluted_eps_history,
    get_dividend_yield_history,
    get_enterprise_value_history,
    get_market_cap_history,
    get_pe_ratio_history,
    get_similar_tickers,
    get_stock_price,
    get_ticker_overview,
    get_ticker_stats,
    get_top_etfs,
    get_top_gainers,
    get_top_losers,
    get_top_performing_tickers,
    get_trending_tickers,
    parallel_map,
)

# Screens available under /markets/stocks/{screen} - the value is the
# fetcher; the key is what the frontend's filter bar and route both use, so
# adding a screen here and to STOCK_SCREENS in the frontend is the whole diff.
STOCK_SCREENS = {
    "most-active": get_most_active_tickers,
    "gainers": get_top_gainers,
    "losers": get_top_losers,
    "top-performing": get_top_performing_tickers,
    "trending": get_trending_tickers,
    "best-historical": get_best_historical_performers,
    "top-etfs": get_top_etfs,
}

# Same pattern as STOCK_SCREENS, but for asset classes that aren't stocks and
# have their own quote shape (options contracts, private-company funding
# data) - kept in separate registries/routes rather than forced into the
# stock table's shape.
OPTIONS_SCREENS = {
    "most-active": get_most_active_options,
    "highest-open-interest": get_highest_open_interest_options,
}

PRIVATE_COMPANY_SCREENS = {
    "highest-valuation": get_highest_valuation_private_companies,
}

# Discovery candidate pool for the Buy Scan (see get_team_scan below): cheap,
# no-LLM screens combined and deduped, so the expensive multi-agent pass only
# runs over a bounded, plausibly-interesting set instead of the whole market.
# Deliberately not just "already hot" screens (most-active/gainers/trending) -
# those bias the pool toward names that already moved, which the synthesizer
# then often (correctly) rates Hold on valuation/risk grounds. Losers and
# long-run historical performers add pullback/quality candidates that don't
# share that bias, so the pool isn't structurally stacked against ever
# finding a Buy.
_SCAN_SCREENS = [
    get_most_active_tickers,
    get_top_gainers,
    get_top_losers,
    get_trending_tickers,
    get_best_historical_performers,
]
_SCAN_CANDIDATES_PER_SCREEN = 15
_SCAN_CANDIDATES_LIMIT = 20


def _scan_candidates() -> list[str]:
    seen = []
    for fetcher in _SCAN_SCREENS:
        items, _ = fetcher(limit=_SCAN_CANDIDATES_PER_SCREEN)
        for item in items:
            ticker = item["ticker"]
            if ticker not in seen:
                seen.append(ticker)
    return seen[:_SCAN_CANDIDATES_LIMIT]


app = FastAPI(title="AI Stock Team API")
app.include_router(auth_router.router)
app.include_router(brokerage_router.router)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    watchlist: list[str] | None = None


def _sse_event_for(item) -> str | None:
    """Map one pydantic-ai stream item to an SSE `event:`/`data:` pair.

    Returns None for event kinds this app's UI doesn't render (e.g. the
    opening PartStartEvent for a non-text part) - the caller skips those.
    """
    match item:
        case FunctionToolCallEvent():
            return format_sse(
                "tool_call",
                json.dumps({"tool_name": item.part.tool_name, "args": item.part.args_as_dict()}),
            )
        case FunctionToolResultEvent():
            content = item.part.content if hasattr(item.part, "content") else None
            return format_sse(
                "tool_result",
                json.dumps({"tool_name": item.part.tool_name, "content": content}, default=str),
            )
        case PartStartEvent(part=TextPart(content=text)) if text:
            return format_sse("text", json.dumps({"delta": text}))
        case PartDeltaEvent(delta=TextPartDelta(content_delta=text)):
            return format_sse("text", json.dumps({"delta": text}))
        case _:
            return None


def _quote(ticker: str) -> dict | None:
    """Returns None for a ticker yfinance doesn't recognize, rather than
    raising - so one bad symbol in a batch (e.g. a mistyped chat mention)
    drops out of the response instead of 500ing the whole request.
    """
    try:
        day_change = get_day_change(ticker)
        return {
            "ticker": ticker,
            "company_name": get_company_name(ticker),
            "price": get_stock_price(ticker),
            "day_change_percent": day_change["percent"],
            "day_change_abs": day_change["absolute"],
            "sparkline": get_sparkline_prices(ticker),
            "day_prices": get_day_prices(ticker),
        }
    except ValueError:
        return None


@app.get("/watchlist")
def get_watchlist(symbols: str | None = None) -> list[dict]:
    """Batched quotes for the default watchlist, or `symbols` if given.

    `symbols` is a comma-separated ticker list - the Dashboard's market
    snapshot strip reuses this same endpoint against index tickers
    (`^GSPC`, `^IXIC`, `^DJI`) instead of the hardcoded watchlist.
    """
    tickers = symbols.split(",") if symbols else DEFAULT_WATCHLIST
    return [quote for quote in parallel_map(_quote, tickers) if quote is not None]


def _compare_quote(ticker: str) -> dict | None:
    """Same drop-bad-symbol behavior as `_quote` - one bad ticker in a
    comparison shouldn't 500 the whole request.
    """
    try:
        return {
            "ticker": ticker,
            "company_name": get_company_name(ticker),
            "price": get_stock_price(ticker),
            "day_change_percent": get_day_change(ticker)["percent"],
            **get_ticker_overview(ticker),
            "price_performance": get_price_performance(ticker),
            "income_statement": get_income_statement(ticker),
            "cash_flow_statement": get_cash_flow_statement(ticker),
            "price_ratios": get_price_ratios(ticker),
        }
    except ValueError:
        return None


@app.get("/tickers/compare")
def get_ticker_comparison(symbols: str) -> list[dict]:
    """Batched comparison quotes for a comma-separated ticker list, for the
    stock comparison page. Plain JSON (no SSE, no LLM call) since this needs
    to render N tickers side by side as fast as /watchlist does, unlike the
    single-ticker /tickers/{ticker} SSE stream.
    """
    tickers = symbols.split(",")
    return [quote for quote in parallel_map(_compare_quote, tickers) if quote is not None]



# Metrics the comparison page can chart per row - the key is what the
# frontend's `historyEndpoint` query param sends; the value is the
# corresponding tools.py history fetcher.
COMPARE_METRICS = {
    "market_cap": get_market_cap_history,
    "enterprise_value": get_enterprise_value_history,
    "pe_ratio": get_pe_ratio_history,
    "diluted_eps": get_diluted_eps_history,
    "dividend_yield": get_dividend_yield_history,
}


def _metric_history(args: tuple[str, str, str, str]) -> dict | None:
    ticker, metric, period, interval = args
    try:
        return {"ticker": ticker, **COMPARE_METRICS[metric](ticker, period=period, interval=interval)}
    except ValueError:
        return None


@app.get("/tickers/compare/history")
def get_ticker_compare_history(
    symbols: str, metric: str, period: str = "1y", interval: str = "1mo"
) -> list[dict]:
    """Batched metric-over-time series for a comma-separated ticker list, for
    the stock comparison page's per-row line charts. `metric` is one of
    COMPARE_METRICS' keys; `interval` is '1mo' (default) or '3mo'.
    """
    fetcher = COMPARE_METRICS.get(metric)
    if fetcher is None:
        raise HTTPException(status_code=404, detail=f"Unknown comparison metric {metric!r}")
    tickers = symbols.split(",")
    results = parallel_map(_metric_history, [(t, metric, period, interval) for t in tickers])
    return [r for r in results if r is not None]


@app.get("/news")
def get_home_news(symbols: str | None = None, category: str | None = None, limit: int = 8) -> list[dict]:
    """Merged recent headlines, for the homepage.

    Ticker source, in priority order: explicit `symbols`, a `category` from
    NEWS_CATEGORY_TICKERS (the homepage's Top Stories/Markets/Tech columns),
    or the watchlist fallback.
    """
    if symbols:
        tickers = symbols.split(",")
    elif category:
        tickers = NEWS_CATEGORY_TICKERS.get(category)
        if tickers is None:
            raise HTTPException(status_code=404, detail=f"Unknown news category: {category}")
    else:
        tickers = DEFAULT_WATCHLIST
    return get_market_news(tickers, limit=limit)


@app.get("/articles/summary")
async def get_article_summary_route(url: str) -> dict:
    """Scrape and summarize a news article, for the "Summarize" button on a
    news row's URL."""
    try:
        summary = await get_article_summary(url)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return summary.model_dump()


def _screen_or_404(registry: dict, screen: str, limit: int) -> list[dict]:
    fetcher = registry.get(screen)
    if fetcher is None:
        raise HTTPException(status_code=404, detail=f"Unknown screen: {screen}")
    return fetcher(limit=limit)


@app.get("/markets/stocks/{screen}")
def get_stock_screen(screen: str, limit: int = 6, offset: int = 0) -> dict:
    """One of STOCK_SCREENS' stock feeds (most-active, gainers, losers,
    top-performing, trending, best-historical, top-etfs), for the homepage's
    movers section and the dedicated /markets/stocks/{screen} page.

    Paginated (unlike the sibling /markets/options and /markets/private-companies
    endpoints, which return a plain list) since these feeds route through
    yfinance's screener, which supports a real `offset` cursor and a `total`
    count of matching results - `{"items": [...], "total": N}` lets the
    frontend build page controls instead of only ever fetching page one.
    """
    fetcher = STOCK_SCREENS.get(screen)
    if fetcher is None:
        raise HTTPException(status_code=404, detail=f"Unknown screen: {screen}")
    items, total = fetcher(limit=limit, offset=offset)
    return {"items": items, "total": total}


@app.get("/markets/options/{screen}")
def get_options_screen(screen: str, limit: int = 6) -> list[dict]:
    """One of OPTIONS_SCREENS' options-contract feeds (most-active,
    highest-open-interest), for the dedicated /markets/options/{screen} page.
    """
    return _screen_or_404(OPTIONS_SCREENS, screen, limit)


@app.get("/markets/private-companies/{screen}")
def get_private_company_screen(screen: str, limit: int = 6) -> list[dict]:
    """One of PRIVATE_COMPANY_SCREENS' private-company feeds
    (highest-valuation), for the dedicated /markets/private-companies/{screen} page.
    """
    return _screen_or_404(PRIVATE_COMPANY_SCREENS, screen, limit)


@app.get("/tickers/team-scan")
async def get_team_scan(user: User = Depends(get_current_user)) -> StreamingResponse:
    """Runs the Stock Team pipeline over a candidate pool pulled from cheap,
    no-LLM screens (see _scan_candidates), so the user can discover buy
    ideas outside their own watchlist/holdings instead of only re-scoring
    tickers they already picked. No `db` dependency here - run_team_scan
    gives each ticker its own session so a few can run concurrently.

    Registered before /tickers/{ticker} below - FastAPI matches routes in
    registration order, and a dynamic {ticker} route would otherwise catch
    this path first and treat "team-scan" as a ticker symbol."""
    candidates = _scan_candidates()

    async def event_source():
        yield format_sse("candidates", json.dumps({"tickers": candidates}))
        try:
            async for result in run_team_scan(candidates, user.id):
                yield format_sse("result", json.dumps(result))
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))

    return StreamingResponse(event_source(), media_type="text/event-stream")


_THEME_PUBLIC_FIELDS = {"key", "name", "description", "risk_level", "source", "industry"}


@app.get("/themes")
def list_themes() -> list[dict]:
    """The fixed theme catalog (see core/themes.py) - static data, no auth
    needed, same as /watchlist. Excludes keywords/tickers, which are
    internal to how get_theme_universe resolves a theme's actual tickers -
    source/industry are exposed so the Themes tab can explain *how* a
    theme's universe gets built, not just show the static description."""
    return [{k: v for k, v in theme.items() if k in _THEME_PUBLIC_FIELDS} for theme in THEME_CATALOG]


@app.get("/themes/{theme_key}/filings-relevance")
def get_theme_filings_relevance(theme_key: str) -> dict[str, dict]:
    """Ticker -> {relevance_score, rationale} for a filings-sourced
    theme's universe (see core/themes.py's get_filings_relevance) - static
    per theme, no auth needed, same as /themes. Empty for a seed/industry
    theme or one the scorer hasn't run for."""
    return get_filings_relevance(theme_key)


@app.get("/themes/{theme_key}/suggestion")
def get_theme_suggestion_route(theme_key: str, db: DbSession = Depends(get_db)) -> dict:
    """The shared model portfolio the Themes tab now renders directly -
    same tickers/weights for every visitor, refreshed on a schedule (see
    agents/theme_builder.py's refresh_theme_suggestion), not per request.
    404 when the theme just hasn't been refreshed yet - an expected,
    common state (most of THEME_CATALOG, until the cron catches up), not
    a real error; the frontend renders a placeholder for it."""
    suggestion = get_theme_suggestion(theme_key, db)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="No suggestion generated yet for this theme")
    return suggestion


@app.get("/themes/{theme_key}/performance")
def get_theme_performance_route(theme_key: str, db: DbSession = Depends(get_db)) -> dict:
    """P/L history reconstructed from real historical closes across every
    version this theme has ever had (see agents/theme_builder.py's
    get_theme_performance) - empty points/updates, not 404, when the
    theme's never been promoted yet, since "no history" is a normal
    state for a theme still on its first live version."""
    return get_theme_performance(theme_key, db)


@app.post("/themes/{theme_key}/suggestion/promote")
def promote_theme_suggestion_route(
    theme_key: str, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> dict:
    """Adopts the pending candidate suggestion as live - the user-facing
    "Update theme" action. Auth-gated (unlike the read side) since it
    mutates shared state every visitor sees, not just the caller's own."""
    try:
        return promote_theme_suggestion(theme_key, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/tickers/{ticker}/history")
def get_ticker_history(ticker: str, period: str = "1mo", benchmark: str | None = None) -> dict:
    ticker = ticker.upper()
    try:
        return {"period": period, **get_sparkline(ticker, period=period, benchmark=benchmark)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/tickers/{ticker}/analyst-ratings")
def get_ticker_analyst_ratings(ticker: str) -> dict:
    return get_analyst_ratings(ticker.upper())


@app.get("/tickers/{ticker}")
async def get_ticker_snapshot(ticker: str) -> StreamingResponse:
    ticker = ticker.upper()

    def _fetch_quote() -> dict:
        return {
            "ticker": ticker,
            "company_name": get_company_name(ticker),
            "price": get_stock_price(ticker),
            "market_cap": get_market_cap(ticker),
            "pe_ratio": get_pe_ratio(ticker),
            "news_headlines": get_news_headlines(ticker),
            "news": get_market_news([ticker], limit=8),
            "similar_tickers": get_similar_tickers(ticker),
            **get_day_change(ticker),
            **get_ticker_stats(ticker),
        }

    async def event_source():
        try:
            # Plain tools.py calls (cached yfinance, no LLM) - sent as one
            # `quote` event immediately so the header/stats/price render
            # without waiting on the sentiment agent below. Offloaded to a
            # thread since these are blocking network calls and this handler
            # is `async def`, so FastAPI won't put it in a threadpool itself -
            # left inline, it would freeze the single event loop and stall
            # every other tab's in-flight request too.
            quote = await asyncio.to_thread(_fetch_quote)
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))
            return
        yield format_sse(
            "quote",
            json.dumps(
                {
                    "ticker": quote["ticker"],
                    "company_name": quote["company_name"],
                    "price": quote["price"],
                    "market_cap": quote["market_cap"],
                    "pe_ratio": quote["pe_ratio"],
                    "day_change_percent": quote["percent"],
                    "day_change_abs": quote["absolute"],
                    "extended_hours": quote["extended_hours"],
                    "news_headlines": quote["news_headlines"],
                    "news": quote["news"],
                    "similar_tickers": quote["similar_tickers"],
                    "fifty_two_week_low": quote["fifty_two_week_low"],
                    "fifty_two_week_high": quote["fifty_two_week_high"],
                    "fifty_two_week_change_percent": quote["fifty_two_week_change_percent"],
                    "volume": quote["volume"],
                    "avg_volume_3m": quote["avg_volume_3m"],
                    "dividend_yield": quote["dividend_yield"],
                    "sector": quote["sector"],
                    "logo_domain": quote["logo_domain"],
                    "forward_pe": quote["forward_pe"],
                    "beta": quote["beta"],
                    "analyst_rating": quote["analyst_rating"],
                    "analyst_target_price": quote["analyst_target_price"],
                    "analyst_target_low": quote["analyst_target_low"],
                    "analyst_target_high": quote["analyst_target_high"],
                    "analyst_count": quote["analyst_count"],
                }
            ),
        )

        try:
            async for item in run_agent_streaming(
                lambda handler: get_sentiment_streaming(
                    ticker, quote["news_headlines"], event_stream_handler=handler
                )
            ):
                if isinstance(item, Final):
                    yield format_sse("sentiment", json.dumps(item.value.model_dump()))
                    continue
                sse_event = _sse_event_for(item)
                if sse_event is not None:
                    yield sse_event
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/tickers/{ticker}/team")
async def get_ticker_team_analysis(
    ticker: str, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> StreamingResponse:
    ticker = ticker.upper()

    async def event_source():
        try:
            async for item in run_agent_streaming(
                lambda handler: get_team_analysis(ticker, event_stream_handler=handler, db=db, user_id=user.id)
            ):
                if isinstance(item, Final):
                    analysis = item.value

                    def _log_verdict() -> None:
                        log_verdict(
                            db,
                            user.id,
                            ticker,
                            get_stock_price(ticker),
                            analysis.verdict,
                            specialist_calls=analysis.specialist_calls,
                        )

                    await asyncio.to_thread(_log_verdict)
                    payload = analysis.verdict.model_dump()
                    payload["is_held"] = analysis.is_held
                    yield format_sse("verdict", json.dumps(payload))
                    continue
                sse_event = _sse_event_for(item)
                if sse_event is not None:
                    yield sse_event
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/track-record")
def get_track_record(
    ticker: str | None = None,
    tickers: str | None = None,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> dict:
    query = select(TeamVerdictRecord).where(TeamVerdictRecord.user_id == user.id)
    if ticker:
        query = query.where(TeamVerdictRecord.ticker == ticker.upper())
    elif tickers:
        symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        query = query.where(TeamVerdictRecord.ticker.in_(symbols))
    query = query.order_by(TeamVerdictRecord.call_date.desc())

    records = score_records(db.execute(query).scalars().all())
    return {"records": records, "stats": aggregate_stats(records)}


@app.get("/track-record/specialists")
def get_specialist_track_record(user: User = Depends(get_current_user), db: DbSession = Depends(get_db)) -> dict:
    """Unlike /track-record, deliberately not ticker-scoped - a specialist's
    calibration is a property of the agent, not of any one ticker."""
    query = select(TeamVerdictRecord).where(TeamVerdictRecord.user_id == user.id)
    records = score_records(db.execute(query).scalars().all())
    return {"specialist_stats": specialist_stats(records)}


@app.post("/chat")
async def post_chat_message(request: ChatRequest) -> StreamingResponse:
    session_id = request.session_id or str(uuid.uuid4())

    async def event_source():
        yield format_sse("session", json.dumps({"session_id": session_id}))
        try:
            async for item in run_agent_streaming(
                lambda handler: send_message(
                    session_id, request.message, watchlist=request.watchlist, event_stream_handler=handler
                )
            ):
                if isinstance(item, Final):
                    continue
                sse_event = _sse_event_for(item)
                if sse_event is not None:
                    yield sse_event
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))

    return StreamingResponse(event_source(), media_type="text/event-stream")
