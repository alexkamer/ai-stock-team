"""Plain functions the agent can call as tools. Registered onto an Agent in config.py."""

from dataclasses import dataclass

import yfinance as yf
from pydantic_ai import RunContext

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
