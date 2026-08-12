"""Plain functions the agent can call as tools. Registered onto an Agent in config.py."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import time
from typing import TypeVar

import requests
import yfinance as yf
from pydantic_ai import RunContext
from yfinance import EquityQuery

# Major US exchange codes yfinance's screener recognizes - used to keep custom
# equity queries (e.g. top-performing) restricted to real US-listed stocks,
# excluding OTC/pink-sheet tickers that would otherwise dominate a raw
# percent-change sort.
_US_MAJOR_EXCHANGES = ["NMS", "NYQ", "NGM", "ASE"]

# Yahoo's predefined-screener endpoint also serves asset classes `yf.screen()`
# doesn't wrap at all (options contracts, private companies) via scrIds that
# aren't in yfinance's PREDEFINED_SCREENER_QUERIES - found by inspecting the
# data-url calls Yahoo's own /markets/options and /markets/private-companies
# pages make. Hitting it directly, same as _TRENDING_URL below.
_PREDEFINED_SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"

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


def get_ticker_stats(ticker: str) -> dict:
    """Look up 52-week range, trading volume, dividend yield, sector, logo
    domain, forward P/E, analyst rating/price target, and beta for a stock
    ticker, for the ticker detail page's hero and expanded stat grid.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    website = info.get("website") or ""
    logo_domain = website.split("//")[-1].split("/")[0].removeprefix("www.") or None
    return {
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_change_percent": info.get("fiftyTwoWeekChangePercent"),
        "volume": info.get("regularMarketVolume"),
        "avg_volume_3m": info.get("averageDailyVolume3Month"),
        "dividend_yield": info.get("dividendYield"),
        "sector": info.get("sector"),
        "logo_domain": logo_domain,
        "forward_pe": info.get("forwardPE"),
        "beta": info.get("beta"),
        "analyst_rating": info.get("averageAnalystRating"),
        "analyst_target_price": info.get("targetMeanPrice"),
        "analyst_target_low": info.get("targetLowPrice"),
        "analyst_target_high": info.get("targetHighPrice"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
    }


def get_ticker_overview(ticker: str) -> dict:
    """Look up valuation, profitability, and company-profile fields for a
    stock ticker, for the stock comparison page's side-by-side tables.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    officers = info.get("companyOfficers") or []
    ceo = next(
        (
            o.get("name")
            for o in officers
            if any(t in (o.get("title") or "").lower() for t in ("chief executive", "ceo"))
        ),
        None,
    )
    return {
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
        "diluted_eps": info.get("trailingEps"),
        "dividend_rate": info.get("dividendRate"),
        "dividend_yield": info.get("dividendYield"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "ceo": ceo,
        "revenue_growth": info.get("revenueGrowth"),
        "gross_margins": info.get("grossMargins"),
        "operating_margins": info.get("operatingMargins"),
        "profit_margins": info.get("profitMargins"),
    }


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


def get_sparkline(ticker: str, period: str = "1mo", benchmark: str | None = None) -> dict:
    """Look up closing prices, volumes, and timestamps for a stock ticker over
    a period, for the ticker detail page's chart. Optionally also fetches a
    benchmark ticker's closes over the same period for a compare overlay.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1d', '5d', '1mo', '6mo', '1y'.
        benchmark: Optional ticker to fetch alongside for a compare overlay, e.g. 'SPY'.
    """
    is_intraday = period in ("1d", "5d")
    interval = {"1d": "5m", "5d": "15m"}.get(period, "1d")
    fmt = {"1d": "%-I:%M %p", "5d": "%b %-d, %-I:%M %p"}.get(period, "%b %-d")

    history = yf.Ticker(ticker).history(period=period, interval=interval, prepost=is_intraday)
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")
    result = {
        "prices": [float(close) for close in history["Close"]],
        "labels": [ts.strftime(fmt) for ts in history.index],
        "volumes": [int(volume) for volume in history["Volume"]],
        "opens": [float(open_) for open_ in history["Open"]],
        "highs": [float(high) for high in history["High"]],
        "lows": [float(low) for low in history["Low"]],
    }
    if is_intraday:
        regular_open, regular_close = time(9, 30), time(16, 0)
        result["is_regular_hours"] = [regular_open <= ts.time() < regular_close for ts in history.index]
    if benchmark:
        bench_history = yf.Ticker(benchmark).history(period=period, interval=interval, prepost=is_intraday)
        if not bench_history.empty:
            result["benchmark_prices"] = [float(close) for close in bench_history["Close"]]
            result["benchmark_ticker"] = benchmark.upper()
    return result


def get_market_cap_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up an approximate market-cap-over-time series for a stock ticker,
    for the stock comparison page's market value line chart.

    yfinance has no historical market-cap endpoint, so this approximates it
    as close price * current shares outstanding - shares outstanding moves
    far less often than price, so this tracks the real series closely over
    the comparison page's typical lookback windows.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1y', '2y', '5y'.
        interval: Bar spacing, e.g. '1mo' or '3mo'.
    """
    info = _get_info(ticker)
    shares_outstanding = info.get("sharesOutstanding")
    if shares_outstanding is None:
        raise ValueError(f"No shares outstanding found for ticker {ticker!r}")

    history = yf.Ticker(ticker).history(period=period, interval=interval)
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")
    fmt = "%b %Y" if interval == "3mo" else "%b '%y"
    return {
        "labels": [ts.strftime(fmt) for ts in history.index],
        "values": [float(close) * float(shares_outstanding) for close in history["Close"]],
    }


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


def _screen_quotes(
    screener_query: str | EquityQuery, limit: int, offset: int = 0, **screen_kwargs
) -> tuple[list[dict], int]:
    """Shared shaping logic for yfinance screeners - either a predefined name
    (most_actives, day_gainers, ...) or a custom `EquityQuery` - each returns
    the same quote fields, just pre-sorted/filtered differently.

    yfinance's `count` param is only honored for predefined queries; custom
    `EquityQuery`/`FundQuery`/`ETFQuery` objects need `size` instead. Both
    accept `offset`, so pagination is a real remote cursor into Yahoo's
    result set, not a local slice of one big fetch - `total` (also from
    Yahoo) tells the caller how many pages exist.

    Over-fetches (`limit * 2`, offset unchanged) since some returned quotes
    get filtered out below for missing symbol/price - without the padding,
    a page would silently return fewer than `limit` tickers instead of
    backfilling from later in the same page.
    """
    fetch_size = limit * 2
    limit_kwarg = {"size": fetch_size} if isinstance(screener_query, EquityQuery) else {"count": fetch_size}
    result = yf.screen(screener_query, offset=offset, **limit_kwarg, **screen_kwargs)
    filtered = [
        quote
        for quote in result.get("quotes", [])
        if quote.get("symbol") and quote.get("regularMarketPrice") is not None
    ][:limit]
    day_prices_by_symbol = dict(
        zip(
            [q["symbol"] for q in filtered],
            parallel_map(get_day_prices, [q["symbol"] for q in filtered]),
        )
    )
    items = [
        {
            "ticker": quote["symbol"],
            "company_name": quote.get("longName") or quote.get("shortName") or quote["symbol"],
            "price": float(quote["regularMarketPrice"]),
            "day_change_abs": quote.get("regularMarketChange"),
            "day_change_percent": float(quote.get("regularMarketChangePercent", 0.0)),
            "fifty_two_week_change_percent": quote.get("fiftyTwoWeekChangePercent"),
            "fifty_two_week_range": quote.get("fiftyTwoWeekRange"),
            "volume": quote.get("regularMarketVolume"),
            "avg_volume_3m": quote.get("averageDailyVolume3Month"),
            "market_cap": quote.get("marketCap"),
            "pe_ratio_ttm": quote.get("trailingPE"),
            "day_prices": day_prices_by_symbol[quote["symbol"]],
        }
        for quote in filtered
    ]
    return items, result.get("total", len(items))


def get_trending_tickers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up tickers with the highest search interest right now, for a
    "trending" feed. Distinct from most-active (trading volume) or top
    gainers/losers (price movement) - this reflects what people are looking
    up, which can lead or lag the other signals.

    Yahoo's trending endpoint mixes in crypto, ETFs, mutual funds, and
    indices alongside stocks, so results are filtered to
    `quoteType == "EQUITY"` to keep this a stocks-only screen - before the
    per-symbol day-chart lookup, so non-equities never trigger a wasted
    "possibly delisted" history fetch.

    Unlike `_screen_quotes`'s screens, Yahoo's trending endpoint ignores any
    offset/start param and always returns its full ranked list (capped
    around 150-180) in one response - so pagination here is a local slice
    of that one fetched pool rather than a fresh remote page per call.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many equities (post-filtering) to skip before `limit`.
    """
    response = requests.get(
        _TRENDING_URL, params={"count": 200}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
    )
    response.raise_for_status()
    results = response.json().get("finance", {}).get("result", [])
    symbols = [q["symbol"] for q in (results[0]["quotes"] if results else []) if q.get("symbol")]

    infos = parallel_map(_get_info, symbols)
    equities = [
        (symbol, info)
        for symbol, info in zip(symbols, infos)
        if info.get("quoteType") == "EQUITY" and (info.get("currentPrice") or info.get("regularMarketPrice"))
    ]
    total = len(equities)
    page = equities[offset : offset + limit]
    day_prices = parallel_map(get_day_prices, [symbol for symbol, _ in page])

    tickers = []
    for (symbol, info), prices in zip(page, day_prices):
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        tickers.append(
            {
                "ticker": symbol,
                "company_name": info.get("longName") or info.get("shortName") or symbol,
                "price": float(price),
                "day_change_abs": info.get("regularMarketChange"),
                "day_change_percent": float(info.get("regularMarketChangePercent", 0.0)),
                "fifty_two_week_change_percent": (
                    info["52WeekChange"] * 100 if info.get("52WeekChange") is not None else None
                ),
                "fifty_two_week_range": info.get("fiftyTwoWeekRange"),
                "volume": info.get("regularMarketVolume"),
                "avg_volume_3m": info.get("averageDailyVolume3Month"),
                "market_cap": info.get("marketCap"),
                "pe_ratio_ttm": info.get("trailingPE"),
                "day_prices": prices,
            }
        )
    return tickers, total


def get_most_active_tickers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up today's highest-trading-volume stocks, for a "most active" feed.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many tickers to skip before `limit`, for pagination.
    """
    return _screen_quotes("most_actives", limit, offset=offset)


def get_top_gainers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up today's biggest stock price gainers, for a "top gainers" feed.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many tickers to skip before `limit`, for pagination.
    """
    return _screen_quotes("day_gainers", limit, offset=offset)


def get_top_losers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up today's biggest stock price losers, for a "top losers" feed.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many tickers to skip before `limit`, for pagination.
    """
    return _screen_quotes("day_losers", limit, offset=offset)


def get_top_performing_tickers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up US stocks with the highest 52-week price % change, for a "top
    performing" feed - a longer-horizon view than today's gainers/losers.
    Restricted to major US exchanges and a market-cap floor so thinly-traded
    OTC tickers (which can show enormous but meaningless % swings) don't
    dominate the list.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many tickers to skip before `limit`, for pagination.
    """
    query = EquityQuery(
        "and",
        [
            EquityQuery("is-in", ["exchange", *_US_MAJOR_EXCHANGES]),
            EquityQuery("gte", ["intradaymarketcap", 2_000_000_000]),
        ],
    )
    return _screen_quotes(query, limit, offset=offset, sortField="fiftytwowkpercentchange", sortAsc=False)


def get_top_etfs(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up today's top-performing US ETFs, for a "top ETFs" feed.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many tickers to skip before `limit`, for pagination.
    """
    return _screen_quotes("top_etfs_us", limit, offset=offset)


def _predefined_screen(scr_id: str, limit: int, fields: list[str]) -> list[dict]:
    """Call Yahoo's predefined-screener endpoint directly for scrIds that
    yfinance's `yf.screen()` doesn't know about (options, private companies).
    Returns the raw `records` list, each value unwrapped from Yahoo's
    `{"raw": ..., "fmt": ...}` shape down to its plain `raw` value.
    """
    response = requests.get(
        _PREDEFINED_SCREENER_URL,
        params={
            "count": limit,
            "scrIds": scr_id,
            "start": 0,
            "useRecordsResponse": "true",
            "fields": ",".join(fields),
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("finance", {}).get("result") or []
    records = results[0].get("records", []) if results else []
    return [
        {key: (value.get("raw") if isinstance(value, dict) else value) for key, value in record.items()}
        for record in records
    ]


def get_most_active_options(limit: int = 6) -> list[dict]:
    """Look up today's highest-trading-volume options contracts across all
    underlyings, for a "most active options" feed.

    Args:
        limit: Maximum number of contracts to return.
    """
    records = _predefined_screen(
        "MOST_ACTIVES_OPTIONS",
        limit,
        [
            "ticker",
            "companyName",
            "underlyingSymbol",
            "strike",
            "expireDate",
            "regularMarketPrice",
            "regularMarketChangePercent",
            "regularMarketVolume",
            "openInterest",
            "impliedVolatility",
        ],
    )
    return [
        {
            "ticker": r["ticker"],
            "company_name": r.get("companyName", r["ticker"]),
            "underlying_symbol": r.get("underlyingSymbol"),
            "strike": r.get("strike"),
            "expire_date": r.get("expireDate"),
            "price": float(r.get("regularMarketPrice") or 0.0),
            "day_change_percent": float(r.get("regularMarketChangePercent") or 0.0),
            "volume": r.get("regularMarketVolume"),
            "open_interest": r.get("openInterest"),
            "implied_volatility": r.get("impliedVolatility"),
        }
        for r in records
    ]


def get_highest_open_interest_options(limit: int = 6) -> list[dict]:
    """Look up today's highest-open-interest options contracts across all
    underlyings, for a "highest open interest" feed - a positioning signal
    distinct from get_most_active_options' trading-volume signal.

    Args:
        limit: Maximum number of contracts to return.
    """
    records = _predefined_screen(
        "TOP_OPTIONS_OPEN_INTEREST",
        limit,
        [
            "ticker",
            "companyName",
            "underlyingSymbol",
            "strike",
            "expireDate",
            "regularMarketPrice",
            "regularMarketChangePercent",
            "regularMarketVolume",
            "openInterest",
            "impliedVolatility",
        ],
    )
    return [
        {
            "ticker": r["ticker"],
            "company_name": r.get("companyName", r["ticker"]),
            "underlying_symbol": r.get("underlyingSymbol"),
            "strike": r.get("strike"),
            "expire_date": r.get("expireDate"),
            "price": float(r.get("regularMarketPrice") or 0.0),
            "day_change_percent": float(r.get("regularMarketChangePercent") or 0.0),
            "volume": r.get("regularMarketVolume"),
            "open_interest": r.get("openInterest"),
            "implied_volatility": r.get("impliedVolatility"),
        }
        for r in records
    ]


def get_highest_valuation_private_companies(limit: int = 6) -> list[dict]:
    """Look up private companies with the highest estimated valuations
    (Anthropic, OpenAI, SpaceX, ...), for a "private companies" feed. Yahoo
    tracks these under synthetic `.PVT` tickers with funding-round data in
    place of exchange-traded quotes.

    Args:
        limit: Maximum number of companies to return.
    """
    records = _predefined_screen(
        "HIGHEST_VALUATION_PRIVATE_COMPANY",
        limit,
        [
            "ticker",
            "companyName",
            "sector",
            "regularMarketPrice",
            "regularMarketChangePercent",
            "fiftyTwoWeekChangePercent",
            "latestImpliedValuation",
            "fundingToDate",
            "latestFundingDate",
            "latestAmountRaised",
            "latestShareClass",
        ],
    )
    return [
        {
            "ticker": r["ticker"],
            "company_name": r.get("companyName", r["ticker"]),
            "sector": r.get("sector"),
            "price": float(r.get("regularMarketPrice") or 0.0),
            "day_change_percent": float(r.get("regularMarketChangePercent") or 0.0),
            "fifty_two_week_change_percent": r.get("fiftyTwoWeekChangePercent"),
            "implied_valuation": r.get("latestImpliedValuation"),
            "funding_to_date": r.get("fundingToDate"),
            "latest_funding_date": r.get("latestFundingDate"),
            "latest_amount_raised": r.get("latestAmountRaised"),
            "latest_share_class": r.get("latestShareClass"),
        }
        for r in records
    ]


def _five_year_change_percent(ticker: str) -> float | None:
    history = yf.Ticker(ticker).history(period="5y", interval="1mo")
    if history.empty or len(history) < 2:
        return None
    first, last = float(history["Close"].iloc[0]), float(history["Close"].iloc[-1])
    return (last - first) / first * 100 if first else None


def get_best_historical_performers(limit: int = 6, offset: int = 0) -> tuple[list[dict], int]:
    """Look up US stocks with the highest 5-year price % change, for a "best
    historical performance" feed - a longer horizon than the 52-week window
    used by get_top_performing_tickers. yfinance has no server-side sort for
    multi-year change, so this re-ranks a pool of 52-week top performers by
    5-year change fetched per-ticker.

    Since the re-rank happens locally (not a remote sort), the candidate
    pool must cover `offset + limit` rather than just `limit`, and paging is
    a slice of that one ranked pool rather than a fresh remote page - so
    `total` reflects the pool size fetched, not every 52-week top performer
    that exists.

    Args:
        limit: Maximum number of tickers to return.
        offset: How many ranked tickers to skip before `limit`, for pagination.
    """
    pool_size = max((offset + limit) * 5, 40)
    candidates, _ = get_top_performing_tickers(limit=pool_size)
    tickers = [c["ticker"] for c in candidates]
    five_year_changes = parallel_map(_five_year_change_percent, tickers)
    for candidate, change in zip(candidates, five_year_changes):
        candidate["five_year_change_percent"] = change
    ranked = sorted(
        (c for c in candidates if c["five_year_change_percent"] is not None),
        key=lambda c: c["five_year_change_percent"],
        reverse=True,
    )
    return ranked[offset : offset + limit], len(ranked)


# Fallback watchlist for a client that hasn't sent one yet (e.g. first
# visit, before the frontend's localStorage-backed list has anything saved).
# There's no per-user storage in this app - the frontend is the source of
# truth for a real watchlist; this only covers the "no list sent" case.
DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]


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
