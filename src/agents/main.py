"""CLI entry point: uv run python main.py TICKER"""

import argparse
import sys

import requests

from core.config import load_agent
from core.models import ArticleSummary, CompanySnapshot, SentimentSummary
from core.tools import get_market_cap, get_news_headlines, get_pe_ratio, get_stock_price, scrape_article

agent = load_agent(tools=[get_stock_price, get_market_cap, get_pe_ratio, get_news_headlines])

# No tools - headlines are handed to it directly in the prompt (the API's
# streaming route already has them from a plain tools.py call), so this is
# one LLM round trip instead of the four `agent` above needs to re-derive
# price/market-cap/P/E/news via tool calls it doesn't actually need here.
sentiment_agent = load_agent()

# Same shape as sentiment_agent - the scraped article text is handed to it
# directly in the prompt rather than as a tool, since the API route already
# has it from a plain tools.py call.
summary_agent = load_agent()


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


async def get_article_summary(url: str) -> ArticleSummary:
    """Scrape an article and summarize it.

    Raises ValueError if the article couldn't be fetched at all - a
    best-effort summary is still produced for a scraped-but-thin/paywalled
    article (the prompt just tells the model what was recovered so it can
    caveat accordingly), but a fetch failure means there's no text to
    summarize in the first place.
    """
    try:
        scraped = scrape_article(url)
    except requests.RequestException as e:
        raise ValueError("Couldn't fetch this article - the site may be blocking automated requests") from e

    if not scraped["text"].strip():
        raise ValueError("No readable text found at this article's URL")

    paywall_note = (
        "Note: this text may be a truncated/paywalled excerpt rather than the full article - "
        "summarize what's here and don't imply you've read more than this.\n\n"
        if scraped["looks_paywalled"]
        else ""
    )
    result = await summary_agent.run(
        f"{paywall_note}Summarize this article in two or three sentences:\n\n{scraped['text']}",
        output_type=ArticleSummary,
    )
    result.output.looks_paywalled = scraped["looks_paywalled"]
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
