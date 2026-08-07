"""Stock Team multi-agent analysis (Lesson 09) wired for the API.

Two narrow specialists (fundamentals, sentiment) plus a synthesizer that
delegates to both and renders a buy/hold/sell verdict. Mirrors
lessons/09_multi_agent_composition.py, but with a structured `TeamVerdict`
output so the API can hand the frontend a badge + reasoning instead of
free text.
"""

from pydantic_ai import RunContext

from core.config import load_agent
from core.models import TeamVerdict
from core.tools import get_market_cap, get_news_headlines, get_pe_ratio, get_stock_price

fundamentals_agent = load_agent(tools=[get_stock_price, get_market_cap, get_pe_ratio])
sentiment_agent = load_agent(tools=[get_news_headlines])
synthesizer = load_agent()


@synthesizer.tool
async def get_fundamentals(ctx: RunContext, ticker: str) -> str:
    """Ask the fundamentals specialist for a ticker's price, market cap, and P/E ratio.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await fundamentals_agent.run(
        f"Report {ticker}'s current price, market cap, and P/E ratio.",
        usage=ctx.usage,
    )
    return result.output


@synthesizer.tool
async def get_sentiment(ctx: RunContext, ticker: str) -> str:
    """Ask the sentiment specialist to judge market mood from recent news on a ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    result = await sentiment_agent.run(
        f"Based on recent headlines, is sentiment on {ticker} bullish, bearish, or neutral? Explain briefly.",
        usage=ctx.usage,
    )
    return result.output


async def get_team_analysis(ticker: str, event_stream_handler=None) -> TeamVerdict:
    result = await synthesizer.run(
        f"Give me a buy/hold/sell take on {ticker}, weighing both the fundamentals and current sentiment.",
        output_type=TeamVerdict,
        event_stream_handler=event_stream_handler,
    )
    return result.output
