"""Tests for tools.py. Mocks yf.Ticker so nothing hits the network."""

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
