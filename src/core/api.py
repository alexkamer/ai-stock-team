"""FastAPI app wrapping the existing agent/tools as HTTP endpoints.

Phase 1 (see WEBAPP_ROADMAP.md): `/tickers/{ticker}/team` and `/chat` stream
via SSE (Lesson 13's event_stream_handler, bridged through sse.py) so the
frontend can render tool-call-in-flight pills and text deltas instead of
blocking on the full agent run.
"""

import json
import uuid

from fastapi import FastAPI, HTTPException
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

from agents.chat import send_message
from agents.main import get_sentiment_streaming
from agents.stock_team import get_team_analysis
from core.sse import Final, format_sse, run_agent_streaming
from core.tools import (
    get_company_name,
    get_day_change,
    get_day_prices,
    get_market_cap,
    get_market_news,
    get_most_active_tickers,
    get_news_headlines,
    get_pe_ratio,
    get_sparkline_prices,
    get_stock_price,
    get_top_gainers,
    get_top_losers,
    get_trending_tickers,
    parallel_map,
)

# Hardcoded default watchlist for v1 - real CRUD is Phase 4.
DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]

app = FastAPI(title="AI Stock Team API")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse_event_for(item) -> str | None:
    """Map one pydantic-ai stream item to an SSE `event:`/`data:` pair.

    Returns None for event kinds this app's UI doesn't render (e.g. the
    opening PartStartEvent for a non-text part) - the caller skips those.
    """
    match item:
        case FunctionToolCallEvent():
            return format_sse("tool_call", json.dumps({"tool_name": item.part.tool_name, "args": item.part.args}))
        case FunctionToolResultEvent():
            content = item.part.content if hasattr(item.part, "content") else None
            return format_sse(
                "tool_result", json.dumps({"tool_name": item.part.tool_name, "content": str(content)})
            )
        case PartStartEvent(part=TextPart(content=text)) if text:
            return format_sse("text", json.dumps({"delta": text}))
        case PartDeltaEvent(delta=TextPartDelta(content_delta=text)):
            return format_sse("text", json.dumps({"delta": text}))
        case _:
            return None


def _quote(ticker: str) -> dict:
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


@app.get("/watchlist")
def get_watchlist(symbols: str | None = None) -> list[dict]:
    """Batched quotes for the default watchlist, or `symbols` if given.

    `symbols` is a comma-separated ticker list - the Dashboard's market
    snapshot strip reuses this same endpoint against index tickers
    (`^GSPC`, `^IXIC`, `^DJI`) instead of the hardcoded watchlist.
    """
    tickers = symbols.split(",") if symbols else DEFAULT_WATCHLIST
    return parallel_map(_quote, tickers)


@app.get("/news")
def get_home_news(symbols: str | None = None, limit: int = 8) -> list[dict]:
    """Merged recent headlines across the watchlist (or `symbols` if given), for the homepage."""
    tickers = symbols.split(",") if symbols else DEFAULT_WATCHLIST
    return get_market_news(tickers, limit=limit)


@app.get("/trending")
def get_trending(limit: int = 6) -> list[dict]:
    """Tickers with the highest search interest right now, for the homepage's trending section."""
    return get_trending_tickers(limit=limit)


@app.get("/most-active")
def get_most_active(limit: int = 6) -> list[dict]:
    """Today's highest-trading-volume stocks, for the homepage's most active section."""
    return get_most_active_tickers(limit=limit)


@app.get("/gainers")
def get_gainers(limit: int = 6) -> list[dict]:
    """Today's biggest stock price gainers, for the homepage's top gainers section."""
    return get_top_gainers(limit=limit)


@app.get("/losers")
def get_losers(limit: int = 6) -> list[dict]:
    """Today's biggest stock price losers, for the homepage's top losers section."""
    return get_top_losers(limit=limit)


@app.get("/tickers/{ticker}/history")
def get_ticker_history(ticker: str, period: str = "1mo") -> dict:
    ticker = ticker.upper()
    try:
        return {"period": period, "prices": get_sparkline_prices(ticker, period=period)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/tickers/{ticker}")
async def get_ticker_snapshot(ticker: str) -> StreamingResponse:
    ticker = ticker.upper()

    async def event_source():
        try:
            # Plain tools.py calls (cached yfinance, no LLM) - sent as one
            # `quote` event immediately so the header/stats/price render
            # without waiting on the sentiment agent below.
            quote = {
                "ticker": ticker,
                "company_name": get_company_name(ticker),
                "price": get_stock_price(ticker),
                "market_cap": get_market_cap(ticker),
                "pe_ratio": get_pe_ratio(ticker),
                "news_headlines": get_news_headlines(ticker),
                **get_day_change(ticker),
            }
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
                    "news_headlines": quote["news_headlines"],
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
async def get_ticker_team_analysis(ticker: str) -> StreamingResponse:
    ticker = ticker.upper()

    async def event_source():
        try:
            async for item in run_agent_streaming(
                lambda handler: get_team_analysis(ticker, event_stream_handler=handler)
            ):
                if isinstance(item, Final):
                    yield format_sse("verdict", json.dumps(item.value.model_dump()))
                    continue
                sse_event = _sse_event_for(item)
                if sse_event is not None:
                    yield sse_event
        except ValueError as e:
            yield format_sse("error", json.dumps({"detail": str(e)}))

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.post("/chat")
async def post_chat_message(request: ChatRequest) -> StreamingResponse:
    session_id = request.session_id or str(uuid.uuid4())

    async def event_source():
        yield format_sse("session", json.dumps({"session_id": session_id}))
        async for item in run_agent_streaming(
            lambda handler: send_message(session_id, request.message, event_stream_handler=handler)
        ):
            if isinstance(item, Final):
                continue
            sse_event = _sse_event_for(item)
            if sse_event is not None:
                yield sse_event

    return StreamingResponse(event_source(), media_type="text/event-stream")
