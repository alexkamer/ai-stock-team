"""CLI entry point: uv run python main.py TICKER"""

import argparse
import sys

from core.config import load_agent
from core.models import CompanySnapshot, SentimentSummary
from core.tools import get_market_cap, get_news_headlines, get_pe_ratio, get_stock_price

agent = load_agent(tools=[get_stock_price, get_market_cap, get_pe_ratio, get_news_headlines])

# No tools - headlines are handed to it directly in the prompt (the API's
# streaming route already has them from a plain tools.py call), so this is
# one LLM round trip instead of the four `agent` above needs to re-derive
# price/market-cap/P/E/news via tool calls it doesn't actually need here.
sentiment_agent = load_agent()


def get_snapshot(ticker: str) -> CompanySnapshot:
    result = agent.run_sync(
        f"Give me a full snapshot of {ticker}: price, market cap, P/E ratio, "
        "and sentiment based on recent news.",
        output_type=CompanySnapshot,
    )
    return result.output


async def get_sentiment_streaming(
    ticker: str, headlines: list[str], event_stream_handler=None
) -> SentimentSummary:
    """Sentiment/summary only, given headlines the caller already fetched.

    The API's Ticker Detail route needs price/market-cap/P/E/news instantly
    (plain tools.py calls, no LLM) and only sentiment actually requires
    reasoning - this is one Bedrock round trip instead of routing everything
    through `agent`'s four-tools-plus-final-answer run.
    """
    headline_list = "\n".join(f"- {h}" for h in headlines)
    result = await sentiment_agent.run(
        f"Based on these recent headlines about {ticker}, is sentiment bullish, "
        f"bearish, or neutral? Give a one or two sentence summary.\n\n{headline_list}",
        output_type=SentimentSummary,
        event_stream_handler=event_stream_handler,
    )
    return result.output


def main() -> None:
    parser = argparse.ArgumentParser(description="Get a stock snapshot for a ticker.")
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. NVDA")
    args = parser.parse_args()

    try:
        snapshot = get_snapshot(args.ticker.upper())
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    print(f"{snapshot.company_name} ({snapshot.ticker})")
    print(f"  Price:      ${snapshot.ticker_price:,.2f}")
    print(f"  Market cap: ${snapshot.market_cap:,.0f}")
    print(f"  P/E ratio:  {snapshot.pe_ratio:.2f}")
    print(f"  Sentiment:  {snapshot.sentiment}")
    print(f"  Summary:    {snapshot.summary}")


if __name__ == "__main__":
    main()
