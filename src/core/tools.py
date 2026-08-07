"""Plain functions the agent can call as tools. Registered onto an Agent in config.py."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

import requests
import yfinance as yf
from pydantic_ai import RunContext

# Yahoo's own "trending" feed - symbols with the highest search interest right
# now. This is a different signal than get_top_gainers/get_top_losers (price
# movers) or _screen_quotes("most_actives", ...) (highest trading volume) -
# yfinance has no wrapper for it, so this hits the endpoint directly.
_TRENDING_URL = "https://query1.finance.yahoo.com/v1/finance/trending/US"

_T = TypeVar("_T")
_R = TypeVar("_R")


def parallel_map(fn: Callable[[_T], _R], items: Iterable[_T]) -> list[_R]:
    """Run `fn` over `items` concurrently on threads, preserving input order.

    Every call here is blocking network I/O (yfinance/requests), so the
    dashboard's per-ticker loops (batched quotes, day charts, merged news)
    would otherwise pay for N sequential round-trips instead of one.
    """
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(len(items), 8)) as executor:
        return list(executor.map(fn, items))


# get_stock_price, get_market_cap, and get_pe_ratio all read from the same
# yf.Ticker(...).info payload. Without this cache, a single query that asks
# for all three (e.g. "price, market cap, and P/E of Nvidia") would trigger
# three separate network fetches of identical data. Keyed by ticker, kept
# for the life of the process - fine for one-shot scripts; a long-running
# service would want a TTL instead.
_info_cache: dict[str, dict] = {}


def _get_info(ticker: str) -> dict:
    if ticker not in _info_cache:
        _info_cache[ticker] = yf.Ticker(ticker).info
    return _info_cache[ticker]


def get_stock_price(ticker: str) -> float:
    """Look up the current/latest market price for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price is None:
        raise ValueError(f"No price found for ticker {ticker!r}")
    return float(price)


def get_market_cap(ticker: str) -> float:
    """Look up the current market capitalization for a stock ticker, in dollars.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    market_cap = info.get("marketCap")
    if market_cap is None:
        raise ValueError(f"No market cap found for ticker {ticker!r}")
    return float(market_cap)


def get_pe_ratio(ticker: str) -> float:
    """Look up the trailing price-to-earnings ratio for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    pe_ratio = info.get("trailingPE") or info.get("forwardPE")
    if pe_ratio is None:
        raise ValueError(f"No P/E ratio found for ticker {ticker!r}")
    return float(pe_ratio)


def get_company_name(ticker: str) -> str:
    """Look up the company name for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    name = info.get("longName") or info.get("shortName")
    if name is None:
        raise ValueError(f"No company name found for ticker {ticker!r}")
    return name


def get_day_change(ticker: str) -> dict:
    """Look up the current day's price change for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.

    Returns:
        A dict with 'percent' and 'absolute' day change, both signed floats.
    """
    info = _get_info(ticker)
    percent = info.get("regularMarketChangePercent")
    absolute = info.get("regularMarketChange")
    if percent is None or absolute is None:
        raise ValueError(f"No day change found for ticker {ticker!r}")
    return {"percent": float(percent), "absolute": float(absolute)}


def get_price_history(ticker: str, period: str = "1mo") -> dict:
    """Summarize price movement for a stock ticker over a period.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1d', '5d', '1mo', '6mo', '1y'.
    """
    history = yf.Ticker(ticker).history(period=period)
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")

    start_price = float(history["Close"].iloc[0])
    end_price = float(history["Close"].iloc[-1])
    return {
        "period": period,
        "start_price": start_price,
        "end_price": end_price,
        "percent_change": (end_price - start_price) / start_price * 100,
        "high": float(history["High"].max()),
        "low": float(history["Low"].min()),
    }


def get_sparkline_prices(ticker: str, period: str = "1mo") -> list[float]:
    """Look up raw closing prices for a stock ticker over a period, for charting.

    Unlike get_price_history (which summarizes into start/end/high/low for
    agent reasoning), this returns every close so a UI can draw a sparkline.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1d', '5d', '1mo', '6mo', '1y'.
    """
    history = yf.Ticker(ticker).history(period=period)
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")
    return [float(close) for close in history["Close"]]


def get_news_headlines(ticker: str, limit: int = 5) -> list[str]:
    """Look up recent news headlines for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        limit: Maximum number of headlines to return.
    """
    articles = yf.Ticker(ticker).news
    headlines = [
        article["content"]["title"]
        for article in articles
        if article.get("content", {}).get("title")
    ]
    if not headlines:
        raise ValueError(f"No news found for ticker {ticker!r}")
    return headlines[:limit]


def get_market_news(tickers: list[str], limit: int = 8) -> list[dict]:
    """Look up recent news across a set of tickers, merged and sorted by recency.

    Unlike get_news_headlines (titles only, for one ticker, for agent
    reasoning), this returns publisher/url/thumbnail too and merges several
    tickers into one feed, for the dashboard's news section.

    Args:
        tickers: Stock ticker symbols to pull headlines from.
        limit: Maximum number of articles to return.
    """
    seen_urls: set[str] = set()
    articles = []
    for ticker_articles in parallel_map(lambda t: yf.Ticker(t).news, tickers):
        for article in ticker_articles:
            content = article.get("content", {})
            title = content.get("title")
            url = content.get("canonicalUrl", {}).get("url")
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            resolutions = (content.get("thumbnail") or {}).get("resolutions") or []
            articles.append(
                {
                    "title": title,
                    "publisher": content.get("provider", {}).get("displayName", ""),
                    "url": url,
                    "published_at": content.get("pubDate", ""),
                    "thumbnail": resolutions[-1]["url"] if resolutions else None,
                }
            )
    articles.sort(key=lambda a: a["published_at"], reverse=True)
    return articles[:limit]


def get_day_prices(ticker: str) -> list[float]:
    """Intraday closes for today, for a small per-row day chart. Best-effort -
    a ticker with no intraday bars yet (e.g. pre-market) gets an empty list
    rather than failing the whole feed it's part of.
    """
    history = yf.Ticker(ticker).history(period="1d", interval="5m")
    return [float(close) for close in history["Close"]] if not history.empty else []


def _screen_quotes(screener_query: str, limit: int) -> list[dict]:
    """Shared shaping logic for yfinance's predefined screeners (most_actives,
    day_gainers, ...) - each returns the same quote fields, just pre-sorted
    differently server-side.
    """
    result = yf.screen(screener_query, count=limit)
    filtered = [
        quote
        for quote in result.get("quotes", [])
        if quote.get("symbol") and quote.get("regularMarketPrice") is not None
    ]
    day_prices_by_symbol = dict(
        zip(
            [q["symbol"] for q in filtered],
            parallel_map(get_day_prices, [q["symbol"] for q in filtered]),
        )
    )
    return [
        {
            "ticker": quote["symbol"],
            "company_name": quote.get("longName") or quote.get("shortName") or quote["symbol"],
            "price": float(quote["regularMarketPrice"]),
            "day_change_percent": float(quote.get("regularMarketChangePercent", 0.0)),
            "volume": quote.get("regularMarketVolume"),
            "day_prices": day_prices_by_symbol[quote["symbol"]],
        }
        for quote in filtered
    ]


def get_trending_tickers(limit: int = 6) -> list[dict]:
    """Look up tickers with the highest search interest right now, for a
    "trending" feed. Distinct from most-active (trading volume) or top
    gainers/losers (price movement) - this reflects what people are looking
    up, which can lead or lag the other signals.

    Args:
        limit: Maximum number of tickers to return.
    """
    response = requests.get(
        _TRENDING_URL, params={"count": limit}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
    )
    response.raise_for_status()
    results = response.json().get("finance", {}).get("result", [])
    symbols = [q["symbol"] for q in (results[0]["quotes"] if results else []) if q.get("symbol")]

    infos = parallel_map(_get_info, symbols)
    day_prices = parallel_map(get_day_prices, symbols)

    tickers = []
    for symbol, info, prices in zip(symbols, infos, day_prices):
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            continue
        tickers.append(
            {
                "ticker": symbol,
                "company_name": info.get("longName") or info.get("shortName") or symbol,
                "price": float(price),
                "day_change_percent": float(info.get("regularMarketChangePercent", 0.0)),
                "volume": info.get("regularMarketVolume"),
                "day_prices": prices,
            }
        )
    return tickers


def get_most_active_tickers(limit: int = 6) -> list[dict]:
    """Look up today's highest-trading-volume stocks, for a "most active" feed.

    Args:
        limit: Maximum number of tickers to return.
    """
    return _screen_quotes("most_actives", limit)


def get_top_gainers(limit: int = 6) -> list[dict]:
    """Look up today's biggest stock price gainers, for a "top gainers" feed.

    Args:
        limit: Maximum number of tickers to return.
    """
    return _screen_quotes("day_gainers", limit)


def get_top_losers(limit: int = 6) -> list[dict]:
    """Look up today's biggest stock price losers, for a "top losers" feed.

    Args:
        limit: Maximum number of tickers to return.
    """
    return _screen_quotes("day_losers", limit)


@dataclass
class Watchlist:
    """Runtime dependency carrying a user's saved tickers.

    Passed as `deps=Watchlist(tickers=[...])` on `agent.run_sync(...)`, not
    hardcoded into a tool - the same agent can serve different users/watchlists
    without redefining any tools.
    """

    tickers: list[str]


def get_watchlist_prices(ctx: RunContext[Watchlist]) -> dict[str, float]:
    """Look up the current price for every ticker on the user's watchlist.

    Takes no arguments from the model - the watchlist comes from `ctx.deps`,
    set once per run via `agent.run_sync(..., deps=Watchlist(...))`.
    """
    return {ticker: get_stock_price(ticker) for ticker in ctx.deps.tickers}
