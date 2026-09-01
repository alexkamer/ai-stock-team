"""Plain functions the agent can call as tools. Registered onto an Agent in config.py."""

import math
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import monotonic
from typing import TypeVar

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
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


# get_stock_price, get_market_cap, get_day_change, and get_pe_ratio all read
# from the same yf.Ticker(...).info payload. Without this cache, a single
# query that asks for all three (e.g. "price, market cap, and P/E of
# Nvidia") would trigger three separate network fetches of identical data.
# Keyed by ticker, with a short TTL rather than the process lifetime - the
# brokerage page polls this repeatedly to auto-refresh prices, and a
# lifetime cache would just keep serving the first-ever quote forever.
_INFO_CACHE_TTL_SECONDS = 20
_info_cache: dict[str, tuple[float, dict]] = {}


def _get_info(ticker: str) -> dict:
    cached = _info_cache.get(ticker)
    if cached is not None and monotonic() - cached[0] < _INFO_CACHE_TTL_SECONDS:
        return cached[1]
    info = yf.Ticker(ticker).info
    _info_cache[ticker] = (monotonic(), info)
    return info


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


def get_sector(ticker: str) -> str:
    """Look up the GICS-style sector for a stock ticker (e.g. 'Technology',
    'Healthcare') - shares _get_info's cache, so calling this right after
    get_stock_price/get_market_cap for the same ticker is effectively free.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    sector = info.get("sector")
    if sector is None:
        raise ValueError(f"No sector found for ticker {ticker!r}")
    return sector


def get_eps(ticker: str) -> float:
    """Look up trailing diluted earnings per share for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    eps = info.get("trailingEps")
    if eps is None:
        raise ValueError(f"No EPS found for ticker {ticker!r}")
    return float(eps)


def get_annualized_volatility(ticker: str, period: str = "1y") -> float:
    """Annualized volatility - the standard deviation of daily returns,
    scaled by sqrt(252) trading days - for a stock ticker. The classic
    "how much does this bounce around" measure, as opposed to beta (which
    measures co-movement with the market rather than raw magnitude).

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: History window to compute volatility over, e.g. '1y'.
    """
    history = yf.Ticker(ticker).history(period=period)
    returns = history["Close"].pct_change().dropna()
    if len(returns) < 2:
        raise ValueError(f"Not enough price history to compute volatility for ticker {ticker!r}")
    return float(returns.std() * math.sqrt(252))


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


def get_analyst_ratings(ticker: str) -> dict:
    """Look up Wall Street analyst consensus for a stock ticker: rating,
    price target range, the current buy/hold/sell breakdown, and the most
    recent rating changes.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    yf_ticker = yf.Ticker(ticker)

    trend = None
    recommendations = yf_ticker.recommendations
    if recommendations is not None and not recommendations.empty:
        current = recommendations.iloc[0]
        trend = {
            "strong_buy": int(current.get("strongBuy", 0)),
            "buy": int(current.get("buy", 0)),
            "hold": int(current.get("hold", 0)),
            "sell": int(current.get("sell", 0)),
            "strong_sell": int(current.get("strongSell", 0)),
        }

    recent_changes = []
    upgrades_downgrades = yf_ticker.upgrades_downgrades
    if upgrades_downgrades is not None and not upgrades_downgrades.empty:
        recent = upgrades_downgrades.sort_index(ascending=False).head(6)
        for graded_at, row in recent.iterrows():
            recent_changes.append({
                "date": graded_at.date().isoformat(),
                "firm": row.get("Firm"),
                "action": row.get("Action"),
                "from_grade": row.get("FromGrade") or None,
                "to_grade": row.get("ToGrade"),
            })

    return {
        "rating": info.get("averageAnalystRating"),
        "target_mean": info.get("targetMeanPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_high": info.get("targetHighPrice"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
        "recommendation_trend": trend,
        "recent_changes": recent_changes,
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
    """Look up the current day's price change for a stock ticker, plus
    pre/post-market price and change if the market is currently in an
    extended session - for the ticker detail page's header, which shows a
    second "pre-market"/"after hours" price line only when one applies.

    Yahoo's `marketState` is one of PREPRE/PRE (before the open),
    REGULAR (during regular hours), POST/POSTPOST (after the close), or
    CLOSED (weekend/holiday, no extended session) - `hasPrePostMarketData`
    additionally gates whether Yahoo actually has a pre/post quote to show,
    which trails the state change briefly right at each session boundary.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.

    Returns:
        A dict with 'percent' and 'absolute' day change (both signed floats,
        vs. regular-session previous close), plus 'extended_hours' - either
        None, or a dict with 'session' ('pre' or 'post'), 'price', and
        signed 'percent'/'absolute' change for that session.
    """
    info = _get_info(ticker)
    percent = info.get("regularMarketChangePercent")
    absolute = info.get("regularMarketChange")
    if percent is None or absolute is None:
        raise ValueError(f"No day change found for ticker {ticker!r}")

    extended_hours = None
    market_state = info.get("marketState")
    if info.get("hasPrePostMarketData"):
        if market_state in ("PRE", "PREPRE") and info.get("preMarketPrice") is not None:
            extended_hours = {
                "session": "pre",
                "price": float(info["preMarketPrice"]),
                "percent": float(info.get("preMarketChangePercent") or 0.0),
                "absolute": float(info.get("preMarketChange") or 0.0),
            }
        elif market_state in ("POST", "POSTPOST") and info.get("postMarketPrice") is not None:
            extended_hours = {
                "session": "post",
                "price": float(info["postMarketPrice"]),
                "percent": float(info.get("postMarketChangePercent") or 0.0),
                "absolute": float(info.get("postMarketChange") or 0.0),
            }

    return {"percent": float(percent), "absolute": float(absolute), "extended_hours": extended_hours}


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


_PRICE_PERFORMANCE_WINDOWS = ["1_week", "1_month", "3_month", "ytd", "1_year"]


def get_price_performance(ticker: str) -> dict:
    """Look up percent price change over several trailing windows (1 week,
    1 month, 3 months, year-to-date, 1 year) for a stock ticker, for the
    stock comparison page's price performance table (and the Themes list
    page's 1-month/1-year return columns).

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    history = yf.Ticker(ticker).history(period="1y")
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")

    closes = history["Close"]
    latest_date = closes.index[-1]
    latest_price = float(closes.iloc[-1])

    # Calendar months/years, not fixed day counts - "3 months ago" means the
    # same day 3 calendar months back (matching how Yahoo Finance and other
    # finance sites compute trailing performance), not day-count
    # approximations like 90 days, which drift onto a different trading day
    # and can flip the sign of the change entirely.
    window_starts = {
        "1_week": latest_date - relativedelta(weeks=1),
        "1_month": latest_date - relativedelta(months=1),
        "3_month": latest_date - relativedelta(months=3),
        "ytd": latest_date.replace(month=1, day=1),
        "1_year": latest_date - relativedelta(years=1),
    }

    result = {}
    for key in _PRICE_PERFORMANCE_WINDOWS:
        start = window_starts[key]
        pos = closes.index.searchsorted(start)
        if pos >= len(closes):
            result[key] = None
            continue
        start_price = float(closes.iloc[pos])
        result[key] = (latest_price - start_price) / start_price * 100
    return result


def _clean_float(value) -> float | None:
    """NaN (insufficient history for a given window) -> None, so callers get
    JSON-serializable output instead of a `NaN` token."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def get_technical_indicators(ticker: str) -> dict:
    """Compute real technical indicators from daily closing prices over the
    trailing year, for the stock team's technicals/risk specialists - grounds
    them in actual computed signals instead of having the model eyeball raw
    price numbers.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    history = yf.Ticker(ticker).history(period="1y")
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")

    closes = history["Close"]
    price = float(closes.iloc[-1])

    sma = {window: _clean_float(closes.rolling(window).mean().iloc[-1]) for window in (20, 50, 200)}

    # RSI (14-day, Wilder's smoothing via an equivalent EWM alpha).
    delta = closes.diff()
    avg_gain = _clean_float(delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().iloc[-1])
    avg_loss = _clean_float((-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().iloc[-1])
    if avg_gain is None or avg_loss is None:
        rsi_14 = None
    elif avg_loss == 0:
        rsi_14 = 100.0 if avg_gain > 0 else 50.0
    else:
        rsi_14 = 100 - (100 / (1 + avg_gain / avg_loss))

    # MACD (12/26 EMA line, 9-period signal line).
    macd_line = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
    macd_signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd = _clean_float(macd_line.iloc[-1])
    macd_signal = _clean_float(macd_signal_line.iloc[-1])

    # 30-day realized volatility, annualized (252 trading days).
    trailing_returns = closes.pct_change().dropna().tail(30)
    volatility_30d_annualized_percent = (
        _clean_float(trailing_returns.std() * (252**0.5) * 100) if len(trailing_returns) >= 2 else None
    )

    return {
        "price": price,
        "sma_20": sma[20],
        "sma_50": sma[50],
        "sma_200": sma[200],
        "above_sma_20": price > sma[20] if sma[20] is not None else None,
        "above_sma_50": price > sma[50] if sma[50] is not None else None,
        "above_sma_200": price > sma[200] if sma[200] is not None else None,
        "golden_cross": sma[50] > sma[200] if sma[50] is not None and sma[200] is not None else None,
        "rsi_14": rsi_14,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_bullish_crossover": macd > macd_signal if macd is not None and macd_signal is not None else None,
        "volatility_30d_annualized_percent": volatility_30d_annualized_percent,
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


def _price_history(ticker: str, period: str, interval: str) -> tuple[list[float], list[str]]:
    """Shared close-price series + formatted date labels for the "derive a
    metric's history from price" helpers below - each of those metrics
    (market cap, enterprise value, P/E, dividend yield) moves almost
    entirely with price over month/quarter timescales, since the other
    factor (shares outstanding, net debt, EPS, dividend rate) changes far
    less often. This is an approximation, not a restatement of history.
    """
    history = yf.Ticker(ticker).history(period=period, interval=interval)
    if history.empty:
        raise ValueError(f"No price history found for ticker {ticker!r}")
    fmt = "%b %Y" if interval == "3mo" else "%b '%y"
    closes = [float(close) for close in history["Close"]]
    labels = [ts.strftime(fmt) for ts in history.index]
    return closes, labels


def get_market_cap_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up an approximate market-cap-over-time series for a stock ticker,
    for the stock comparison page's market value chart.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1y', '2y', '5y'.
        interval: Bar spacing, e.g. '1mo' or '3mo'.
    """
    info = _get_info(ticker)
    shares_outstanding = info.get("sharesOutstanding")
    if shares_outstanding is None:
        raise ValueError(f"No shares outstanding found for ticker {ticker!r}")

    closes, labels = _price_history(ticker, period, interval)
    return {
        "labels": labels,
        "values": [close * float(shares_outstanding) for close in closes],
    }


def get_enterprise_value_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up an approximate enterprise-value-over-time series for a stock
    ticker, for the stock comparison page's enterprise value chart.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1y', '2y', '5y'.
        interval: Bar spacing, e.g. '1mo' or '3mo'.
    """
    info = _get_info(ticker)
    shares_outstanding = info.get("sharesOutstanding")
    total_debt = info.get("totalDebt")
    total_cash = info.get("totalCash")
    if shares_outstanding is None or total_debt is None or total_cash is None:
        raise ValueError(f"No enterprise value inputs found for ticker {ticker!r}")
    net_debt = float(total_debt) - float(total_cash)

    closes, labels = _price_history(ticker, period, interval)
    return {
        "labels": labels,
        "values": [close * float(shares_outstanding) + net_debt for close in closes],
    }


def get_pe_ratio_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up an approximate price-to-earnings-over-time series for a stock
    ticker, for the stock comparison page's P/E chart.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1y', '2y', '5y'.
        interval: Bar spacing, e.g. '1mo' or '3mo'.
    """
    info = _get_info(ticker)
    eps = info.get("trailingEps")
    if not eps:
        raise ValueError(f"No trailing EPS found for ticker {ticker!r}")

    closes, labels = _price_history(ticker, period, interval)
    return {
        "labels": labels,
        "values": [close / float(eps) for close in closes],
    }


def get_dividend_yield_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up an approximate forward-dividend-yield-over-time series for a
    stock ticker, for the stock comparison page's dividend & yield chart.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: How far back to look, e.g. '1y', '2y', '5y'.
        interval: Bar spacing, e.g. '1mo' or '3mo'.
    """
    info = _get_info(ticker)
    dividend_rate = info.get("dividendRate")
    if not dividend_rate:
        raise ValueError(f"No dividend rate found for ticker {ticker!r}")

    closes, labels = _price_history(ticker, period, interval)
    return {
        "labels": labels,
        "values": [float(dividend_rate) / close * 100 for close in closes],
    }


def get_diluted_eps_history(ticker: str, period: str = "1y", interval: str = "1mo") -> dict:
    """Look up reported quarterly diluted EPS for a stock ticker, for the
    stock comparison page's diluted EPS chart.

    Unlike the other comparison history helpers, this isn't derived from
    price - it's yfinance's actual reported quarterly income statement
    figures, so `interval` is ignored (always quarterly) and the lookback
    is whatever quarters yfinance has on hand (usually the trailing ~5).

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        period: Unused - kept for a consistent signature with the other history helpers.
        interval: Unused - kept for a consistent signature with the other history helpers.
    """
    statement = yf.Ticker(ticker).quarterly_income_stmt
    if statement is None or statement.empty or "Diluted EPS" not in statement.index:
        raise ValueError(f"No quarterly diluted EPS found for ticker {ticker!r}")
    row = statement.loc["Diluted EPS"].dropna().sort_index()
    if row.empty:
        raise ValueError(f"No quarterly diluted EPS found for ticker {ticker!r}")
    return {
        "labels": [f"Q{(ts.month - 1) // 3 + 1} {ts.year}" for ts in row.index],
        "values": [float(v) for v in row],
    }


def get_income_statement(ticker: str) -> dict:
    """Look up the most recent annual revenue, operating expenses, operating
    income, gross profit, and year-over-year revenue growth for a stock
    ticker, for the stock comparison page's income statement table.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    statement = yf.Ticker(ticker).income_stmt
    if statement is None or statement.empty:
        raise ValueError(f"No income statement found for ticker {ticker!r}")

    latest_period = statement.columns[0]

    def field(name: str) -> float | None:
        if name not in statement.index:
            return None
        value = statement.loc[name, latest_period]
        return float(value) if value is not None and value == value else None  # NaN != NaN

    # Revenue growth comes from `info.revenueGrowth` (most recent quarter vs.
    # the same quarter a year ago) rather than diffing the two most recent
    # *annual* columns above - that's what Yahoo Finance's "Revenue Growth"
    # stat shows, and a company's latest quarter can grow YoY even in a year
    # its full fiscal-year revenue declined (or vice versa), so the two
    # aren't interchangeable.
    info = _get_info(ticker)
    revenue_growth_fraction = info.get("revenueGrowth")

    return {
        "revenue": field("Total Revenue"),
        "operating_expenses": field("Operating Expense"),
        "operating_income": field("Operating Income"),
        "gross_profit": field("Gross Profit"),
        "revenue_growth_yoy": revenue_growth_fraction * 100 if revenue_growth_fraction is not None else None,
    }


def get_cash_flow_statement(ticker: str) -> dict:
    """Look up trailing-twelve-month operating cash flow, capital
    expenditures, investing cash flow, and free cash flow for a stock
    ticker, for the stock comparison page's cash flow table.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    statement = yf.Ticker(ticker).quarterly_cash_flow
    if statement is None or statement.empty:
        raise ValueError(f"No cash flow statement found for ticker {ticker!r}")

    # TTM (sum of the 4 most recent quarters), matching what finance sites
    # show as "current" cash flow figures - the latest single annual column
    # can be many months stale (e.g. NVDA's most recent fiscal year ended
    # Jan 2026, while the TTM through Apr 2026 shows meaningfully higher
    # free cash flow as the business kept growing quarter over quarter).
    last_4_quarters = statement.columns[:4]

    def field(name: str) -> float | None:
        if name not in statement.index:
            return None
        values = statement.loc[name, last_4_quarters].dropna()
        return float(values.sum()) if len(values) == len(last_4_quarters) else None

    return {
        "operating_cash_flow": field("Operating Cash Flow"),
        "capital_expenditures": field("Capital Expenditure"),
        "investing_cash_flow": field("Investing Cash Flow"),
        "free_cash_flow": field("Free Cash Flow"),
    }


def get_price_ratios(ticker: str) -> dict:
    """Look up trailing and forward P/E, price-to-free-cash-flow, price-to-book,
    price-to-sales, and EV/EBITDA for a stock ticker, for the stock
    comparison page's price ratios table.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
    """
    info = _get_info(ticker)
    ticker_obj = yf.Ticker(ticker)

    # yfinance's own `forwardPE`/`forwardEps` fields use the *next* fiscal
    # year's consensus EPS estimate ("+1y" in `earnings_estimate`), but
    # Yahoo Finance's displayed "Forward P/E" uses the *current* fiscal
    # year's estimate ("0y") - a full estimate-year earlier. Using
    # `forwardPE` directly understates forward P/E (e.g. showed 17.4 for
    # NVDA against Yahoo's ~21-25 depending on as-of date); price / the "0y"
    # estimate matches Yahoo's convention.
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    forward_pe = None
    if price:
        try:
            current_year_eps_estimate = ticker_obj.earnings_estimate.loc["0y", "avg"]
        except (KeyError, AttributeError):
            current_year_eps_estimate = None
        if current_year_eps_estimate:
            forward_pe = price / current_year_eps_estimate

    # Price-to-free-cash-flow has no direct yfinance field, unlike the other
    # five ratios below - derive it as market cap / free cash flow (equal to
    # price-per-share / FCF-per-share, but avoids needing shares outstanding
    # as a separate input).
    price_to_fcf = None
    market_cap = info.get("marketCap")
    if market_cap:
        try:
            free_cash_flow = get_cash_flow_statement(ticker).get("free_cash_flow")
        except ValueError:
            free_cash_flow = None
        if free_cash_flow:
            price_to_fcf = market_cap / free_cash_flow

    return {
        "pe_ratio": info.get("trailingPE"),
        "forward_pe_ratio": forward_pe,
        "price_to_fcf": price_to_fcf,
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
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



# yfinance's `.news` property only pulls the latest 10 stories per ticker
# (~1 hour of coverage on an active ticker). Asking get_news() for more
# directly gives get_market_news a several-hour pool to pick "best" articles
# from and still leave a real remainder for the More News overflow.
NEWS_FETCH_COUNT = 30


# Publishers found (via scripts/news_scrape_coverage.py) to be essentially
# never readable past the headline - Motley Fool paywalls almost every
# article, TheStreet's yfinance-supplied URLs 404 in practice, and Barron's/
# WSJ are hard subscriber paywalls with no workaround. Penalized in ranking
# and used to skip the doomed "Summarize" attempt client-side.
LOW_READABILITY_PUBLISHERS = {"Motley Fool", "TheStreet", "Barrons.com", "The Wall Street Journal"}

# Big enough to outweigh the max possible editors-pick+thumbnail bonus (3),
# so a low-readability article never outranks an unadorned readable one.
_LOW_READABILITY_PENALTY = 4


def _article_quality_score(article: dict) -> int:
    """Editorial/visual quality signal used to rank "best" over "newest" -
    Yahoo's own editors' pick flag counts most, a thumbnail (needed for the
    carousel/card treatments anyway) counts a little, and a known-unreadable
    publisher counts heavily against. Ties fall back to recency via
    get_market_news' stable sort."""
    score = (2 if article["_editors_pick"] else 0) + (1 if article["thumbnail"] else 0)
    if article["publisher"] in LOW_READABILITY_PUBLISHERS:
        score -= _LOW_READABILITY_PENALTY
    return score


# Matches on this after lowercasing/stripping punctuation - wire stories
# (Reuters/AP/Bloomberg) routinely get pulled into several tickers' feeds
# verbatim under different publisher domains and canonical URLs, so URL-only
# dedup lets the same headline occupy multiple slots in the ranked pool.
_TITLE_DEDUPE_RE = re.compile(r"[^a-z0-9]+")


def _dedupe_title_key(title: str) -> str:
    return _TITLE_DEDUPE_RE.sub(" ", title.lower()).strip()


# Articles older than this rarely matter for a "what's moving now" feed, so
# they're dropped before ranking rather than merely tie-broken behind fresher
# ones - otherwise a high-quality but week-old story can permanently occupy a
# slot on a quiet ticker. Only applied when doing so still leaves enough
# articles to fill the requested limit, since illiquid tickers can have thin,
# sparse news where the alternative is an empty feed.
_MAX_ARTICLE_AGE = timedelta(days=7)


def _article_age(article: dict) -> timedelta:
    try:
        published = date_parser.isoparse(article["published_at"])
    except (ValueError, TypeError):
        return timedelta(0)
    now = datetime.now(published.tzinfo) if published.tzinfo else datetime.utcnow()
    return now - published


def get_market_news(tickers: list[str], limit: int = 8) -> list[dict]:
    """Look up the best recent news across a set of tickers, for the homepage.

    Unlike get_news_headlines (titles only, for one ticker, for agent
    reasoning), this returns publisher/url/thumbnail too and merges several
    tickers into one feed. Each article is tagged with the ticker whose feed
    it came from plus that ticker's day change, so the UI can show a "NVDA
    +3.03%" style badge; if the same story also turned up in other tickers'
    feeds (same title, different URL - typically a syndicated wire story),
    those are collapsed into this one entry and listed under
    `related_tickers` instead of appearing as separate duplicate articles.
    Ranked by quality (see _article_quality_score) rather than pure recency,
    so a caller taking a small `limit` gets the best of the pool fetched
    rather than just whatever posted most recently - callers that want
    "everything else" should fetch a much larger `limit` against the same
    tickers and filter out what a "best of" call already returned. Articles
    from LOW_READABILITY_PUBLISHERS are down-ranked (a real headline is still
    worth showing) and flagged `likely_unreadable` so a "Summarize" UI can
    skip the doomed scrape attempt.

    Args:
        tickers: Stock ticker symbols to pull headlines from.
        limit: Maximum number of articles to return.
    """
    seen_urls: set[str] = set()
    raw_articles = []
    fetch = lambda t: yf.Ticker(t).get_news(count=NEWS_FETCH_COUNT)
    for ticker, ticker_articles in zip(tickers, parallel_map(fetch, tickers)):
        for article in ticker_articles:
            content = article.get("content", {})
            title = content.get("title")
            url = content.get("canonicalUrl", {}).get("url")
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            resolutions = (content.get("thumbnail") or {}).get("resolutions") or []
            best = max(resolutions, key=lambda r: r.get("width", 0), default=None)
            raw_articles.append(
                {
                    "title": title,
                    "summary": content.get("summary") or None,
                    "publisher": content.get("provider", {}).get("displayName", ""),
                    "url": url,
                    "published_at": content.get("pubDate", ""),
                    "thumbnail": best["url"] if best else None,
                    "ticker": ticker,
                    "is_video": content.get("contentType") == "VIDEO",
                    "_editors_pick": bool((content.get("metadata") or {}).get("editorsPick")),
                }
            )

    groups: dict[str, list[dict]] = {}
    for article in raw_articles:
        groups.setdefault(_dedupe_title_key(article["title"]), []).append(article)

    articles = []
    for group in groups.values():
        best = max(group, key=_article_quality_score)
        best["related_tickers"] = sorted({a["ticker"] for a in group} - {best["ticker"]})
        articles.append(best)

    fresh_articles = [a for a in articles if _article_age(a) <= _MAX_ARTICLE_AGE]
    if len(fresh_articles) >= limit:
        articles = fresh_articles

    articles.sort(key=lambda a: a["published_at"], reverse=True)
    articles.sort(key=_article_quality_score, reverse=True)
    articles = articles[:limit]
    for article in articles:
        del article["_editors_pick"]

    unique_tickers = sorted({a["ticker"] for a in articles} | {t for a in articles for t in a["related_tickers"]})
    day_changes = {}
    for ticker, change in zip(unique_tickers, parallel_map(_try_day_change, unique_tickers)):
        if change is not None:
            day_changes[ticker] = change
    for article in articles:
        article["ticker_day_change_percent"] = day_changes.get(article["ticker"])
        article["related_tickers"] = [
            {"ticker": t, "day_change_percent": day_changes.get(t)} for t in article["related_tickers"]
        ]
        article["likely_unreadable"] = article["is_video"] or article["publisher"] in LOW_READABILITY_PUBLISHERS

    return articles


def _try_day_change(ticker: str) -> float | None:
    try:
        return get_day_change(ticker)["percent"]
    except ValueError:
        return None


# Phrases that show up in the gate/teaser text publishers leave behind when
# the rest of an article is cut off - checked case-insensitively against the
# scraped text as a cheap paywall signal, no LLM call needed.
_PAYWALL_PHRASES = [
    "subscribe to continue",
    "subscribe to read",
    "sign in to continue",
    "sign in to read",
    "log in to continue",
    "already a subscriber",
    "create a free account to",
    "to continue reading",
    "this content is for subscribers",
    "become a member to",
]

# Below this word count a scraped article is almost certainly a teaser/stub
# rather than the real body, regardless of gate phrases.
_PAYWALL_MIN_WORDS = 80


def scrape_article(url: str) -> dict:
    """Fetch an article URL and extract its main text.

    Args:
        url: Article URL, typically from get_market_news's `url` field.
    """
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    container = soup.find("article") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n".join(p for p in paragraphs if p)

    word_count = len(text.split())
    lowered = text.lower()
    looks_paywalled = word_count < _PAYWALL_MIN_WORDS or any(phrase in lowered for phrase in _PAYWALL_PHRASES)

    return {"text": text, "word_count": word_count, "looks_paywalled": looks_paywalled}


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


def _canonical_screener_value(field: str, value: str) -> str | None:
    """A quote's `info["industry"]`/`info["sector"]` (e.g. "Software -
    Application") is spelled slightly differently than yfinance's screener
    EQ allow-list for the same field (e.g. "Software—Application", an em
    dash with no surrounding spaces) - normalize dashes on both sides to
    find the exact string EquityQuery will accept. Returns None if there's
    no match at all (field unrecognized, or a value the screener has no
    equivalent for), so the caller can skip that field instead of
    constructing a query that will raise.
    """
    from yfinance.const import EQUITY_SCREENER_EQ_MAP

    allowed = EQUITY_SCREENER_EQ_MAP.get(field)
    if allowed is None:
        return None
    candidates = allowed if isinstance(allowed, set) else {v for values in allowed.values() for v in values}

    def _normalize_dashes(s: str) -> str:
        return re.sub(r"\s*[-–—]\s*", "—", s).casefold()

    normalized_value = _normalize_dashes(value)
    for candidate in candidates:
        if _normalize_dashes(candidate) == normalized_value:
            return candidate
    return None


def get_similar_tickers(ticker: str, limit: int = 8) -> list[dict]:
    """Look up peer stocks in the same industry, for the ticker detail
    page's "Similar tickers" sidebar. Restricted to major US exchanges and
    a market-cap floor, same as get_top_performing_tickers, so thinly-traded
    OTC peers don't crowd out real comparables.

    Falls back to the broader sector if the industry alone doesn't have
    enough peers above the market-cap floor (e.g. a niche industry with
    only one or two other listed players). Returns an empty list rather
    than raising for tickers with no industry/sector at all (ETFs, indices),
    or one whose industry/sector value the screener has no equivalent for
    - unlike get_pe_ratio etc., this is a supplementary sidebar, not a value
    the rest of the ticker detail page depends on.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        limit: Maximum number of peers to return.
    """
    info = _get_info(ticker)
    industry = info.get("industry")
    sector = info.get("sector")
    if not industry and not sector:
        return []

    def _peers(field: str, value: str) -> list[dict]:
        canonical_value = _canonical_screener_value(field, value)
        if canonical_value is None:
            return []
        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", [field, canonical_value]),
                EquityQuery("is-in", ["exchange", *_US_MAJOR_EXCHANGES]),
                EquityQuery("gte", ["intradaymarketcap", 2_000_000_000]),
            ],
        )
        items, _ = _screen_quotes(query, limit + 1, sortField="intradaymarketcap", sortAsc=False)
        return [item for item in items if item["ticker"] != ticker][:limit]

    peers = _peers("industry", industry) if industry else []
    if len(peers) < limit and sector:
        peers = _peers("sector", sector)
    return peers


def screen_by_industry(industry: str, min_market_cap: float = 2_000_000_000, limit: int = 15) -> list[str]:
    """Look up the largest US-listed tickers in a given yfinance industry
    classification, for building a Theme's ticker universe from live data
    instead of a hand-picked list. Same building blocks as
    get_similar_tickers's _peers() (canonical value translation, exchange +
    market-cap floor, sorted by market cap descending) but keyed by a
    human-readable industry name directly rather than derived from an
    existing ticker's `.info`.

    Args:
        industry: Human-readable industry name, e.g. 'Semiconductors'.
        min_market_cap: Market-cap floor in dollars, to exclude thinly-traded names.
        limit: Maximum number of tickers to return.
    """
    canonical = _canonical_screener_value("industry", industry)
    if canonical is None:
        raise ValueError(f"No screener equivalent for industry {industry!r}")
    query = EquityQuery(
        "and",
        [
            EquityQuery("eq", ["industry", canonical]),
            EquityQuery("is-in", ["exchange", *_US_MAJOR_EXCHANGES]),
            EquityQuery("gte", ["intradaymarketcap", min_market_cap]),
        ],
    )
    items, _ = _screen_quotes(query, limit, sortField="intradaymarketcap", sortAsc=False)
    return [item["ticker"] for item in items]


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

# Curated ticker sets used to source the homepage's category news columns.
# yfinance's news payload carries no topic tags, so "category" here just
# means "which tickers' headlines feed this column" - see get_market_news.
NEWS_CATEGORY_TICKERS = {
    "top": DEFAULT_WATCHLIST + ["TSLA", "^GSPC"],
    "markets": ["^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "GC=F", "CL=F"],
    "tech": ["NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMD", "AVGO", "ORCL"],
}

# "More News" pulls from the union of every category above, so it's a
# broader pool the homepage can filter down to whatever wasn't already
# shown in the carousel/list/category columns, rather than a distinct
# ticker set of its own.
NEWS_CATEGORY_TICKERS["more"] = sorted(
    {t for tickers in NEWS_CATEGORY_TICKERS.values() for t in tickers}
)


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
