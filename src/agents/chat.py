"""Research Chat agent + server-side session state (Phase 0/1).

One agent, a dynamic system prompt injecting today's date and the user's
watchlist (Lesson 08), and message history threaded per session (Lesson 05).
Sessions live in an in-memory dict keyed by UUID - restart clears them,
which is fine for v1 per WEBAPP_ROADMAP.md.
"""

from datetime import date

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage

from core.config import load_agent
from core.tools import (
    Watchlist,
    get_company_name,
    get_day_change,
    get_market_cap,
    get_news_headlines,
    get_pe_ratio,
    get_price_history,
    get_stock_price,
    get_watchlist_prices,
)

DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]

agent = load_agent(
    tools=[
        get_stock_price,
        get_market_cap,
        get_pe_ratio,
        get_company_name,
        get_day_change,
        get_price_history,
        get_news_headlines,
        get_watchlist_prices,
    ],
    deps_type=Watchlist,
)


@agent.system_prompt
def add_context(ctx: RunContext[Watchlist]) -> str:
    return f"Today's date is {date.today().isoformat()}. The user's watchlist is {ctx.deps.tickers}."


# session_id -> accumulated message history (all_messages() output).
_sessions: dict[str, list[ModelMessage]] = {}


async def send_message(session_id: str, text: str, event_stream_handler=None) -> str:
    history = _sessions.get(session_id, [])
    result = await agent.run(
        text,
        message_history=history,
        deps=Watchlist(tickers=DEFAULT_WATCHLIST),
        event_stream_handler=event_stream_handler,
    )
    _sessions[session_id] = result.all_messages()
    return result.output
