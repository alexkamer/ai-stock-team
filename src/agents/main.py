"""CLI entry point: uv run python main.py TICKER"""

import argparse
import sys
from time import monotonic

import requests

from sqlalchemy.orm import Session as DbSession

from core.config import load_agent
from core.llm_usage import log_llm_usage
from core.models import ArticleSummary, CompanySnapshot, PortfolioDigest, SentimentSummary
from core.tools import get_market_cap, get_news_headlines, get_pe_ratio, get_stock_price, scrape_article

agent = load_agent(tools=[get_stock_price, get_market_cap, get_pe_ratio, get_news_headlines])

# No tools - headlines are handed to it directly in the prompt (the API's
# streaming route already has them from a plain tools.py call), so this is
# one LLM round trip instead of the four `agent` above needs to re-derive
# price/market-cap/P/E/news via tool calls it doesn't actually need here.
sentiment_agent = load_agent()

# Ticker Detail fires this on every page load with no caching upstream, so
# repeat visits to the same ticker re-pay a Bedrock round trip for a read
# that's cheap to reuse - same TTL-cache idiom as tools.py's _info_cache.
# Keyed by (ticker, headlines) rather than ticker alone so a genuinely new
# headline set invalidates the cache immediately regardless of TTL.
_SENTIMENT_CACHE_TTL_SECONDS = 15 * 60
_sentiment_cache: dict[tuple[str, tuple[str, ...]], tuple[float, SentimentSummary]] = {}

# Same shape as sentiment_agent - the scraped article text is handed to it
# directly in the prompt rather than as a tool, since the API route already
# has it from a plain tools.py call.
summary_agent = load_agent()

# Same no-tools shape - the caller assembles holdings + news context up
# front (see routers/brokerage.py's _build_digest_context) so this is one
# round trip rather than an agentic loop re-deriving prices/news via tools,
# which is the whole point given this is meant to be user-triggered, not run
# on a schedule. config.yaml's default max_tokens (1024) is too small for a
# real article, so this overrides it per-call rather than raising the
# shared default for every other agent.
digest_agent = load_agent()
_DIGEST_MODEL_SETTINGS = {"max_tokens": 4096}


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

    Cached per (ticker, headlines) for _SENTIMENT_CACHE_TTL_SECONDS - a cache
    hit returns immediately without touching event_stream_handler, which
    run_agent_streaming's caller already handles fine (no stream events, just
    the final result).
    """
    cache_key = (ticker, tuple(headlines))
    cached = _sentiment_cache.get(cache_key)
    if cached is not None and monotonic() - cached[0] < _SENTIMENT_CACHE_TTL_SECONDS:
        return cached[1]

    headline_list = "\n".join(f"- {h}" for h in headlines)
    result = await sentiment_agent.run(
        f"Based on these recent headlines about {ticker}, is sentiment bullish, "
        f"bearish, or neutral? Give a one or two sentence summary.\n\n{headline_list}",
        output_type=SentimentSummary,
        event_stream_handler=event_stream_handler,
    )
    _sentiment_cache[cache_key] = (monotonic(), result.output)
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


async def get_portfolio_digest(
    context: str, db: DbSession | None = None, user_id: int | None = None
) -> PortfolioDigest:
    """Write an in-depth daily digest article from a pre-assembled context
    string (holdings performance + relevant news, see
    routers/brokerage.py's _build_digest_context) - one Bedrock round trip,
    no tools, since the caller already did all the data gathering.

    db/user_id are optional so this stays callable without a DB session -
    when passed, the real per-call cost is logged via core.llm_usage."""
    result = await digest_agent.run(
        "You are writing a daily portfolio digest for a retail investor, based only on the data below - "
        "don't invent holdings, prices, or news not present in it. Explain *why* the portfolio moved the "
        "way it did today, citing specific holdings and news where the data supports it, and flag what's "
        "worth watching next (unresolved news threads, upcoming catalysts, concentration risk). Write the "
        "article as plain prose in a measured, non-sensational tone - paragraphs separated by a blank "
        "line, no markdown headers.\n\n"
        "Each news item below is labeled with a bracketed number, like [1]. Whenever a sentence in the "
        "article, or a key_drivers/watch_items bullet, relies on one of these news items, cite it inline "
        "immediately after that sentence using its exact bracketed number, e.g. 'demand concerns [2].' "
        "Never invent a citation number that isn't labeled below. Claims based purely on the portfolio's "
        "own price/value data (no news backing) don't need a citation.\n\n"
        f"{context}",
        output_type=PortfolioDigest,
        model_settings=_DIGEST_MODEL_SETTINGS,
    )
    if db is not None:
        log_llm_usage(db, user_id, "digest", result.usage)
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
