"""Tests for tools.py. Mocks yf.Ticker so nothing hits the network."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core import tools


@pytest.fixture(autouse=True)
def clear_info_cache():
    # get_stock_price/get_market_cap/get_pe_ratio share tools._info_cache,
    # keyed by ticker - clear it so tests using the same ticker string don't
    # see another test's mocked info dict.
    tools._info_cache.clear()
    yield
    tools._info_cache.clear()


def make_ticker(info=None, news=None, history=None):
    """Build a MagicMock standing in for yf.Ticker(...)'s return value."""
    ticker = MagicMock()
    ticker.info = info or {}
    ticker.news = news or []
    ticker.get_news.return_value = news or []
    ticker.history.return_value = history if history is not None else pd.DataFrame()
    return ticker


@patch("core.tools.yf.Ticker")
def test_get_stock_price_uses_current_price(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"currentPrice": 123.45})

    price = tools.get_stock_price("NVDA")

    assert price == 123.45
    mock_ticker_cls.assert_called_once_with("NVDA")


@patch("core.tools.yf.Ticker")
def test_get_stock_price_falls_back_to_regular_market_price(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"regularMarketPrice": 67.89})

    price = tools.get_stock_price("AAPL")

    assert price == 67.89


@patch("core.tools.yf.Ticker")
def test_get_stock_price_raises_when_no_price_available(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    with pytest.raises(ValueError, match="No price found"):
        tools.get_stock_price("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_market_cap_returns_value(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"marketCap": 4_785_098_457_088})

    market_cap = tools.get_market_cap("NVDA")

    assert market_cap == 4_785_098_457_088.0


@patch("core.tools.yf.Ticker")
def test_get_market_cap_raises_when_missing(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    with pytest.raises(ValueError, match="No market cap found"):
        tools.get_market_cap("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_pe_ratio_prefers_trailing_pe(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"trailingPE": 30.3, "forwardPE": 25.1})

    pe_ratio = tools.get_pe_ratio("NVDA")

    assert pe_ratio == 30.3


@patch("core.tools.yf.Ticker")
def test_get_pe_ratio_falls_back_to_forward_pe(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"forwardPE": 25.1})

    pe_ratio = tools.get_pe_ratio("NVDA")

    assert pe_ratio == 25.1


@patch("core.tools.yf.Ticker")
def test_get_pe_ratio_raises_when_missing(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    with pytest.raises(ValueError, match="No P/E ratio found"):
        tools.get_pe_ratio("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_info_is_fetched_once_and_shared_across_tools(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info={"currentPrice": 197.84, "marketCap": 4.78e12, "trailingPE": 30.3}
    )

    tools.get_stock_price("NVDA")
    tools.get_market_cap("NVDA")
    tools.get_pe_ratio("NVDA")

    mock_ticker_cls.assert_called_once_with("NVDA")


@patch("core.tools.yf.Ticker")
def test_info_cache_is_scoped_per_ticker(mock_ticker_cls):
    mock_ticker_cls.side_effect = lambda ticker: make_ticker(
        info={"currentPrice": 100.0} if ticker == "AAA" else {"currentPrice": 200.0}
    )

    price_a = tools.get_stock_price("AAA")
    price_b = tools.get_stock_price("BBB")

    assert price_a == 100.0
    assert price_b == 200.0
    assert mock_ticker_cls.call_count == 2


@patch("core.tools.yf.Ticker")
def test_get_price_history_summarizes_ohlc(mock_ticker_cls):
    history = pd.DataFrame(
        {
            "Close": [100.0, 105.0, 110.0],
            "High": [101.0, 106.0, 112.0],
            "Low": [99.0, 103.0, 108.0],
        }
    )
    mock_ticker_cls.return_value = make_ticker(history=history)

    summary = tools.get_price_history("NVDA", period="1mo")

    assert summary == {
        "period": "1mo",
        "start_price": 100.0,
        "end_price": 110.0,
        "percent_change": 10.0,
        "high": 112.0,
        "low": 99.0,
    }


@patch("core.tools.yf.Ticker")
def test_get_price_history_raises_when_empty(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame())

    with pytest.raises(ValueError, match="No price history found"):
        tools.get_price_history("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_company_name_prefers_long_name(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"longName": "NVIDIA Corporation", "shortName": "NVIDIA"})

    name = tools.get_company_name("NVDA")

    assert name == "NVIDIA Corporation"


@patch("core.tools.yf.Ticker")
def test_get_company_name_falls_back_to_short_name(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={"shortName": "NVIDIA"})

    name = tools.get_company_name("NVDA")

    assert name == "NVIDIA"


@patch("core.tools.yf.Ticker")
def test_get_company_name_raises_when_missing(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    with pytest.raises(ValueError, match="No company name found"):
        tools.get_company_name("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_day_change_returns_percent_and_absolute(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        info={"regularMarketChangePercent": 1.8, "regularMarketChange": 2.34}
    )

    change = tools.get_day_change("NVDA")

    assert change == {"percent": 1.8, "absolute": 2.34}


@patch("core.tools.yf.Ticker")
def test_get_day_change_raises_when_missing(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    with pytest.raises(ValueError, match="No day change found"):
        tools.get_day_change("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_sparkline_prices_returns_all_closes(mock_ticker_cls):
    history = pd.DataFrame({"Close": [100.0, 105.0, 110.0]})
    mock_ticker_cls.return_value = make_ticker(history=history)

    sparkline = tools.get_sparkline_prices("NVDA", period="1mo")

    assert sparkline == [100.0, 105.0, 110.0]


@patch("core.tools.yf.Ticker")
def test_get_sparkline_prices_raises_when_empty(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame())

    with pytest.raises(ValueError, match="No price history found"):
        tools.get_sparkline_prices("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_sparkline_returns_prices_labels_and_volumes(mock_ticker_cls):
    history = pd.DataFrame(
        {
            "Open": [99.0, 103.0, 108.0],
            "High": [101.0, 106.0, 111.0],
            "Low": [98.0, 102.0, 107.0],
            "Close": [100.0, 105.0, 110.0],
            "Volume": [1_000, 2_000, 1_500],
        },
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    mock_ticker_cls.return_value = make_ticker(history=history)

    result = tools.get_sparkline("NVDA", period="1mo")

    assert result["prices"] == [100.0, 105.0, 110.0]
    assert result["volumes"] == [1000, 2000, 1500]
    assert result["opens"] == [99.0, 103.0, 108.0]
    assert result["highs"] == [101.0, 106.0, 111.0]
    assert result["lows"] == [98.0, 102.0, 107.0]
    assert result["labels"] == ["Jan 1", "Jan 2", "Jan 3"]
    assert "benchmark_prices" not in result


@patch("core.tools.yf.Ticker")
def test_get_sparkline_flags_regular_hours_for_intraday_periods(mock_ticker_cls):
    history = pd.DataFrame(
        {
            "Open": [99.0, 103.0, 108.0],
            "High": [101.0, 106.0, 111.0],
            "Low": [98.0, 102.0, 107.0],
            "Close": [100.0, 105.0, 110.0],
            "Volume": [1_000, 2_000, 1_500],
        },
        index=pd.DatetimeIndex(["2024-01-02 08:00", "2024-01-02 10:00", "2024-01-02 17:00"]),
    )
    mock_ticker_cls.return_value = make_ticker(history=history)

    result = tools.get_sparkline("NVDA", period="1d")

    assert result["is_regular_hours"] == [False, True, False]
    mock_ticker_cls.return_value.history.assert_called_once_with(period="1d", interval="5m", prepost=True)


@patch("core.tools.yf.Ticker")
def test_get_sparkline_omits_regular_hours_for_daily_periods(mock_ticker_cls):
    history = pd.DataFrame(
        {"Open": [99.0], "High": [101.0], "Low": [98.0], "Close": [100.0], "Volume": [1_000]},
        index=pd.date_range("2024-01-01", periods=1, freq="D"),
    )
    mock_ticker_cls.return_value = make_ticker(history=history)

    result = tools.get_sparkline("NVDA", period="1mo")

    assert "is_regular_hours" not in result


@patch("core.tools.yf.Ticker")
def test_get_sparkline_raises_when_empty(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame())

    with pytest.raises(ValueError, match="No price history found"):
        tools.get_sparkline("BADTICKER")


@patch("core.tools.yf.Ticker")
def test_get_sparkline_includes_benchmark_when_given(mock_ticker_cls):
    history = pd.DataFrame(
        {"Open": [99.0, 104.0], "High": [101.0, 106.0], "Low": [98.0, 103.0], "Close": [100.0, 105.0], "Volume": [1_000, 2_000]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    bench_history = pd.DataFrame(
        {"Open": [499.0, 505.0], "High": [502.0, 511.0], "Low": [497.0, 504.0], "Close": [500.0, 510.0], "Volume": [9_000, 9_500]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    mock_ticker_cls.side_effect = lambda symbol: (
        make_ticker(history=bench_history) if symbol == "spy" else make_ticker(history=history)
    )

    result = tools.get_sparkline("NVDA", period="1mo", benchmark="spy")

    assert result["benchmark_prices"] == [500.0, 510.0]
    assert result["benchmark_ticker"] == "SPY"


@patch("core.tools.yf.Ticker")
def test_get_sparkline_omits_benchmark_when_empty(mock_ticker_cls):
    history = pd.DataFrame(
        {"Open": [99.0, 104.0], "High": [101.0, 106.0], "Low": [98.0, 103.0], "Close": [100.0, 105.0], "Volume": [1_000, 2_000]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    mock_ticker_cls.side_effect = lambda symbol: (
        make_ticker(history=pd.DataFrame()) if symbol == "BADBENCH" else make_ticker(history=history)
    )

    result = tools.get_sparkline("NVDA", period="1mo", benchmark="BADBENCH")

    assert "benchmark_prices" not in result
    assert "benchmark_ticker" not in result


@patch("core.tools.yf.Ticker")
def test_get_day_prices_returns_intraday_closes(mock_ticker_cls):
    history = pd.DataFrame({"Close": [100.0, 101.5, 99.8]})
    mock_ticker_cls.return_value = make_ticker(history=history)

    day_prices = tools.get_day_prices("NVDA")

    assert day_prices == [100.0, 101.5, 99.8]
    mock_ticker_cls.return_value.history.assert_called_once_with(period="1d", interval="5m")


@patch("core.tools.yf.Ticker")
def test_get_day_prices_returns_empty_list_when_no_intraday_bars(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame())

    assert tools.get_day_prices("NVDA") == []


def make_article(title):
    return {"content": {"title": title}}


@patch("core.tools.yf.Ticker")
def test_get_news_headlines_extracts_titles(mock_ticker_cls):
    articles = [make_article("Headline one"), make_article("Headline two")]
    mock_ticker_cls.return_value = make_ticker(news=articles)

    headlines = tools.get_news_headlines("NVDA")

    assert headlines == ["Headline one", "Headline two"]


@patch("core.tools.yf.Ticker")
def test_get_news_headlines_respects_limit(mock_ticker_cls):
    articles = [make_article(f"Headline {i}") for i in range(10)]
    mock_ticker_cls.return_value = make_ticker(news=articles)

    headlines = tools.get_news_headlines("NVDA", limit=3)

    assert headlines == ["Headline 0", "Headline 1", "Headline 2"]


@patch("core.tools.yf.Ticker")
def test_get_news_headlines_skips_articles_without_titles(mock_ticker_cls):
    articles = [{"content": {}}, make_article("Real headline")]
    mock_ticker_cls.return_value = make_ticker(news=articles)

    headlines = tools.get_news_headlines("NVDA")

    assert headlines == ["Real headline"]


@patch("core.tools.yf.Ticker")
def test_get_news_headlines_raises_when_no_news(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(news=[])

    with pytest.raises(ValueError, match="No news found"):
        tools.get_news_headlines("BADTICKER")


def make_news_article(title, url, publisher="Yahoo Finance", published_at="2026-08-07T12:00:00Z", thumbnail_url=None):
    content = {
        "title": title,
        "canonicalUrl": {"url": url},
        "provider": {"displayName": publisher},
        "pubDate": published_at,
    }
    if thumbnail_url:
        content["thumbnail"] = {"resolutions": [{"url": thumbnail_url}]}
    return {"content": content}


@patch("core.tools.yf.Ticker")
def test_get_market_news_returns_articles_sorted_newest_first(mock_ticker_cls):
    def side_effect(ticker):
        news_by_ticker = {
            "NVDA": [make_news_article("NVDA older", "https://example.com/nvda", published_at="2026-08-07T09:00:00Z")],
            "AAPL": [make_news_article("AAPL newer", "https://example.com/aapl", published_at="2026-08-07T12:00:00Z")],
        }
        return make_ticker(news=news_by_ticker[ticker])

    mock_ticker_cls.side_effect = side_effect

    articles = tools.get_market_news(["NVDA", "AAPL"])

    assert [a["title"] for a in articles] == ["AAPL newer", "NVDA older"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_dedupes_by_url_across_tickers(mock_ticker_cls):
    shared = make_news_article("Shared story", "https://example.com/shared")
    mock_ticker_cls.return_value = make_ticker(news=[shared])

    articles = tools.get_market_news(["NVDA", "AAPL"])

    assert len(articles) == 1


@patch("core.tools.yf.Ticker")
def test_get_market_news_respects_limit(mock_ticker_cls):
    articles = [make_news_article(f"Headline {i}", f"https://example.com/{i}") for i in range(10)]
    mock_ticker_cls.return_value = make_ticker(news=articles)

    result = tools.get_market_news(["NVDA"], limit=3)

    assert len(result) == 3


@patch("core.tools.yf.Ticker")
def test_get_market_news_includes_publisher_and_thumbnail(mock_ticker_cls):
    article = make_news_article(
        "Headline", "https://example.com/a", publisher="Reuters", thumbnail_url="https://example.com/thumb.jpg"
    )
    mock_ticker_cls.return_value = make_ticker(news=[article])

    [result] = tools.get_market_news(["NVDA"])

    assert result["publisher"] == "Reuters"
    assert result["thumbnail"] == "https://example.com/thumb.jpg"
    assert result["url"] == "https://example.com/a"


@patch("core.tools.yf.Ticker")
def test_get_market_news_skips_articles_without_title_or_url(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(
        news=[{"content": {}}, make_news_article("Real headline", "https://example.com/real")]
    )

    articles = tools.get_market_news(["NVDA"])

    assert [a["title"] for a in articles] == ["Real headline"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_merges_syndicated_duplicate_titles(mock_ticker_cls):
    # Same wire story, different publisher/URL under each ticker's feed -
    # should collapse into one entry crediting both tickers, not two
    # separate articles.
    def side_effect(ticker):
        news_by_ticker = {
            "NVDA": [make_news_article("Fed cuts rates by 25bps", "https://reuters.com/a", publisher="Reuters")],
            "AAPL": [make_news_article("Fed Cuts Rates By 25bps!", "https://apnews.com/b", publisher="AP")],
        }
        return make_ticker(news=news_by_ticker[ticker])

    mock_ticker_cls.side_effect = side_effect

    articles = tools.get_market_news(["NVDA", "AAPL"])

    assert len(articles) == 1
    [article] = articles
    assert article["ticker"] == "NVDA"
    assert [r["ticker"] for r in article["related_tickers"]] == ["AAPL"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_drops_stale_articles_when_enough_fresh_remain(mock_ticker_cls):
    now = datetime.now(timezone.utc)
    fresh = make_news_article(
        "Fresh headline", "https://example.com/fresh", published_at=now.isoformat().replace("+00:00", "Z")
    )
    stale = make_news_article(
        "Stale headline",
        "https://example.com/stale",
        published_at=(now - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
    )
    mock_ticker_cls.return_value = make_ticker(news=[fresh, stale])

    articles = tools.get_market_news(["NVDA"], limit=1)

    assert [a["title"] for a in articles] == ["Fresh headline"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_keeps_stale_articles_when_pool_too_thin(mock_ticker_cls):
    now = datetime.now(timezone.utc)
    stale = make_news_article(
        "Only headline",
        "https://example.com/only",
        published_at=(now - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
    )
    mock_ticker_cls.return_value = make_ticker(news=[stale])

    articles = tools.get_market_news(["NVDA"], limit=8)

    assert [a["title"] for a in articles] == ["Only headline"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_down_ranks_low_readability_publishers(mock_ticker_cls):
    unreadable = make_news_article(
        "Unreadable headline", "https://example.com/unreadable", publisher="Motley Fool", thumbnail_url="https://x/t.jpg"
    )
    readable = make_news_article("Readable headline", "https://example.com/readable", publisher="Reuters")
    mock_ticker_cls.return_value = make_ticker(news=[unreadable, readable])

    articles = tools.get_market_news(["NVDA"], limit=1)

    assert [a["title"] for a in articles] == ["Readable headline"]


@patch("core.tools.yf.Ticker")
def test_get_market_news_flags_likely_unreadable_publishers(mock_ticker_cls):
    article = make_news_article("Headline", "https://example.com/a", publisher="TheStreet")
    mock_ticker_cls.return_value = make_ticker(news=[article])

    [result] = tools.get_market_news(["NVDA"])

    assert result["likely_unreadable"] is True


def make_quote(symbol, price=100.0, change_percent=1.5, volume=1_000_000, name=None):
    return {
        "symbol": symbol,
        "longName": name or f"{symbol} Corp",
        "regularMarketPrice": price,
        "regularMarketChangePercent": change_percent,
        "regularMarketVolume": volume,
    }


def make_trending_response(symbols):
    response = MagicMock()
    response.json.return_value = {"finance": {"result": [{"quotes": [{"symbol": s} for s in symbols]}]}}
    return response


@patch("core.tools.yf.Ticker")
@patch("core.tools.requests.get")
def test_get_trending_tickers_enriches_symbols_with_quote_data(mock_get, mock_ticker_cls):
    mock_get.return_value = make_trending_response(["NVDA"])
    mock_ticker_cls.return_value = make_ticker(
        info={"currentPrice": 219.78, "longName": "NVIDIA Corporation", "regularMarketChangePercent": 0.26},
        history=pd.DataFrame({"Close": [217.0, 219.78]}),
    )

    trending = tools.get_trending_tickers()

    assert trending == [
        {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "price": 219.78,
            "day_change_percent": 0.26,
            "volume": None,
            "day_prices": [217.0, 219.78],
        }
    ]
    mock_get.assert_called_once_with(
        tools._TRENDING_URL, params={"count": 6}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
    )
    mock_ticker_cls.return_value.history.assert_called_with(period="1d", interval="5m")


@patch("core.tools.yf.Ticker")
@patch("core.tools.requests.get")
def test_get_trending_tickers_respects_limit(mock_get, mock_ticker_cls):
    mock_get.return_value = make_trending_response([])

    tools.get_trending_tickers(limit=3)

    mock_get.assert_called_once_with(
        tools._TRENDING_URL, params={"count": 3}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
    )


@patch("core.tools.yf.Ticker")
@patch("core.tools.requests.get")
def test_get_trending_tickers_skips_symbols_without_a_price(mock_get, mock_ticker_cls):
    mock_get.return_value = make_trending_response(["AAA", "BBB"])
    mock_ticker_cls.side_effect = lambda ticker: make_ticker(
        info={} if ticker == "AAA" else {"currentPrice": 50.0, "longName": "BBB Corp"}
    )

    trending = tools.get_trending_tickers()

    assert [t["ticker"] for t in trending] == ["BBB"]


@patch("core.tools.yf.Ticker")
@patch("core.tools.requests.get")
def test_get_trending_tickers_returns_empty_list_when_no_symbols(mock_get, mock_ticker_cls):
    mock_get.return_value = make_trending_response([])

    assert tools.get_trending_tickers() == []
    mock_ticker_cls.assert_not_called()


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_most_active_tickers_extracts_quotes(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {"quotes": [make_quote("NVDA", price=219.78, change_percent=0.26, volume=5_000_000)]}
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [217.0, 219.78]}))

    most_active = tools.get_most_active_tickers()

    assert most_active == [
        {
            "ticker": "NVDA",
            "company_name": "NVDA Corp",
            "price": 219.78,
            "day_change_percent": 0.26,
            "volume": 5_000_000,
            "day_prices": [217.0, 219.78],
        }
    ]
    mock_screen.assert_called_once_with("most_actives", count=6)


@patch("core.tools.yf.screen")
def test_get_most_active_tickers_respects_limit(mock_screen):
    mock_screen.return_value = {"quotes": []}

    tools.get_most_active_tickers(limit=3)

    mock_screen.assert_called_once_with("most_actives", count=3)


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_top_gainers_extracts_quotes(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {"quotes": [make_quote("SPCX", price=131.55, change_percent=14.47, volume=210_927_255)]}
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [120.0, 131.55]}))

    gainers = tools.get_top_gainers()

    assert gainers == [
        {
            "ticker": "SPCX",
            "company_name": "SPCX Corp",
            "price": 131.55,
            "day_change_percent": 14.47,
            "volume": 210_927_255,
            "day_prices": [120.0, 131.55],
        }
    ]
    mock_screen.assert_called_once_with("day_gainers", count=6)


@patch("core.tools.yf.screen")
def test_get_top_gainers_respects_limit(mock_screen):
    mock_screen.return_value = {"quotes": []}

    tools.get_top_gainers(limit=3)

    mock_screen.assert_called_once_with("day_gainers", count=3)


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_top_losers_extracts_quotes(mock_screen, mock_ticker_cls):
    mock_screen.return_value = {"quotes": [make_quote("XYZ", price=12.34, change_percent=-9.87, volume=8_000_000)]}
    mock_ticker_cls.return_value = make_ticker(history=pd.DataFrame({"Close": [14.0, 12.34]}))

    losers = tools.get_top_losers()

    assert losers == [
        {
            "ticker": "XYZ",
            "company_name": "XYZ Corp",
            "price": 12.34,
            "day_change_percent": -9.87,
            "volume": 8_000_000,
            "day_prices": [14.0, 12.34],
        }
    ]
    mock_screen.assert_called_once_with("day_losers", count=6)


@patch("core.tools.yf.screen")
def test_get_top_losers_respects_limit(mock_screen):
    mock_screen.return_value = {"quotes": []}

    tools.get_top_losers(limit=3)

    mock_screen.assert_called_once_with("day_losers", count=3)


def make_ctx(watchlist):
    # get_watchlist_prices only reads ctx.deps, so a bare stand-in with that
    # one attribute is enough - no need to construct a real RunContext.
    ctx = MagicMock()
    ctx.deps = watchlist
    return ctx


@patch("core.tools.yf.Ticker")
def test_get_watchlist_prices_looks_up_every_ticker(mock_ticker_cls):
    mock_ticker_cls.side_effect = lambda ticker: make_ticker(
        info={"currentPrice": {"NVDA": 200.0, "AAPL": 345.0, "MSFT": 397.0}[ticker]}
    )
    watchlist = tools.Watchlist(tickers=["NVDA", "AAPL", "MSFT"])

    prices = tools.get_watchlist_prices(make_ctx(watchlist))

    assert prices == {"NVDA": 200.0, "AAPL": 345.0, "MSFT": 397.0}


@patch("core.tools.yf.Ticker")
def test_get_watchlist_prices_empty_watchlist_returns_empty_dict(mock_ticker_cls):
    watchlist = tools.Watchlist(tickers=[])

    prices = tools.get_watchlist_prices(make_ctx(watchlist))

    assert prices == {}
    mock_ticker_cls.assert_not_called()


@patch("core.tools.yf.Ticker")
@patch("core.tools.yf.screen")
def test_get_similar_tickers_normalizes_dash_style_before_querying(mock_screen, mock_ticker_cls):
    # Yahoo's quote info spells this "Software - Application" (hyphen with
    # spaces); yfinance's screener EQ allow-list only accepts the em-dash,
    # no-space form - get_similar_tickers must translate rather than pass
    # the info-dict spelling straight through, or EquityQuery raises.
    mock_ticker_cls.return_value = make_ticker(info={"industry": "Software - Application", "sector": "Technology"})
    mock_screen.return_value = {
        "quotes": [
            make_quote("SAP", price=250.0),
            make_quote("NVDA", price=219.78),
        ]
    }

    peers = tools.get_similar_tickers("NVDA", limit=5)

    assert [p["ticker"] for p in peers] == ["SAP"]
    industry_query = mock_screen.call_args_list[0].args[0]
    assert "Software—Application" in str(industry_query)


@patch("core.tools.yf.Ticker")
def test_get_similar_tickers_returns_empty_list_without_industry_or_sector(mock_ticker_cls):
    mock_ticker_cls.return_value = make_ticker(info={})

    assert tools.get_similar_tickers("SPY") == []
