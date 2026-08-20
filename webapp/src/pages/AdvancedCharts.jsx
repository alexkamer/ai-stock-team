import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import { useWatchlist } from '../context/WatchlistContext'
import './AdvancedCharts.css'

// How many tickers to show in the auto-populated (non-watchlist) sections -
// these are lists that could otherwise grow unbounded (holdings, trending,
// analysis history), so each is capped to keep the sidebar scannable.
const SECTION_LIMIT = 8

const TV_SCRIPT_SRC = 'https://s3.tradingview.com/tv.js'
const CONTAINER_ID = 'advanced-charts-tv-container'
const DEFAULT_SYMBOL = 'AAPL'
const STORAGE_KEY = 'advanced-charts-symbol'

// A starter indicator set so the chart opens with real technical context
// instead of a bare price line - all free studies built into the widget.
const DEFAULT_STUDIES = ['MASimple@tv-basicstudies', 'Volume@tv-basicstudies', 'RSI@tv-basicstudies']

const COMPARE_PRESETS = [
  { symbol: 'SPY', label: 'S&P 500' },
  { symbol: 'QQQ', label: 'Nasdaq 100' },
  { symbol: 'DIA', label: 'Dow 30' },
]

// No exchange info is available anywhere in this app's API, so we pass
// bare tickers straight through - TradingView resolves the right listing
// (e.g. "JPM" -> NYSE:JPM) on its own. An explicit "EXCHANGE:TICKER" input
// is passed through unchanged.
function normalizeSymbol(value) {
  const trimmed = value.trim().toUpperCase()
  return trimmed || null
}

function loadTradingViewScript() {
  if (window.TradingView) return Promise.resolve()
  if (!window.__tvScriptPromise) {
    window.__tvScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = TV_SCRIPT_SRC
      script.async = true
      script.onload = resolve
      script.onerror = reject
      document.body.appendChild(script)
    })
  }
  return window.__tvScriptPromise
}

function loadPersistedSymbol() {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function SidebarSection({ title, tickers, emptyMessage, activeTicker, onSelect, quotes }) {
  return (
    <div className="advanced-charts__sidebar-section">
      <h3 className="advanced-charts__sidebar-title">{title}</h3>
      {tickers === null ? (
        <ul className="advanced-charts__watchlist">
          {[0, 1, 2].map((i) => (
            <li key={i} className="advanced-charts__ticker-row advanced-charts__ticker-row--loading" />
          ))}
        </ul>
      ) : tickers.length === 0 ? (
        <p className="advanced-charts__sidebar-empty">{emptyMessage}</p>
      ) : (
        <ul className="advanced-charts__watchlist">
          {tickers.map((t) => {
            const q = quotes[t]
            const positive = (q?.day_change_percent ?? 0) >= 0
            return (
              <li key={t}>
                <button
                  type="button"
                  className={`advanced-charts__ticker-row${t === activeTicker ? ' advanced-charts__ticker-row--active' : ''}`}
                  onClick={() => onSelect(t)}
                >
                  <span className="advanced-charts__ticker-name">
                    <span className="advanced-charts__ticker-symbol">{t}</span>
                    {q?.company_name ? (
                      <span className="advanced-charts__ticker-company">{q.company_name}</span>
                    ) : null}
                  </span>
                  {q ? (
                    <span className="advanced-charts__ticker-meta">
                      <span className="advanced-charts__ticker-price num">{q.price.toFixed(2)}</span>
                      <span
                        className={`advanced-charts__ticker-change num ${positive ? 'advanced-charts__ticker-change--good' : 'advanced-charts__ticker-change--bad'}`}
                      >
                        {positive ? '+' : ''}
                        {q.day_change_percent.toFixed(2)}%
                      </span>
                    </span>
                  ) : null}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default function AdvancedCharts() {
  const { tickers } = useWatchlist()
  const [portfolioTickers, setPortfolioTickers] = useState(null)
  const [trendingTickers, setTrendingTickers] = useState(null)
  const [analyzedTickers, setAnalyzedTickers] = useState(null)
  const [quotes, setQuotes] = useState({})
  const [searchParams, setSearchParams] = useSearchParams()
  const [symbol, setSymbolState] = useState(
    () =>
      normalizeSymbol(searchParams.get('symbol') ?? '') ??
      loadPersistedSymbol() ??
      tickers[0] ??
      DEFAULT_SYMBOL,
  )
  const [searchInput, setSearchInput] = useState('')
  const [compareSymbols, setCompareSymbols] = useState([])
  const containerRef = useRef(null)

  function setSymbol(next) {
    setSymbolState(next)
    setSearchParams({ symbol: next }, { replace: true })
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage unavailable (private browsing, quota) - just won't persist
    }
  }

  useEffect(() => {
    if (searchParams.get('symbol') !== symbol) {
      setSearchParams({ symbol }, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let cancelled = false
    getJSON('/brokerage/portfolio')
      .then((data) => {
        if (cancelled) return
        const symbols = [...new Set(data.positions.map((p) => p.symbol))]
        setPortfolioTickers(symbols.slice(0, SECTION_LIMIT))
      })
      .catch(() => !cancelled && setPortfolioTickers([]))
    getJSON('/markets/stocks/trending')
      .then((data) => !cancelled && setTrendingTickers(data.items.map((t) => t.ticker).slice(0, SECTION_LIMIT)))
      .catch(() => !cancelled && setTrendingTickers([]))
    getJSON('/track-record')
      .then((data) => {
        if (cancelled) return
        const symbols = [...new Set(data.records.map((r) => r.ticker))]
        setAnalyzedTickers(symbols.slice(0, SECTION_LIMIT))
      })
      .catch(() => !cancelled && setAnalyzedTickers([]))
    return () => {
      cancelled = true
    }
  }, [])

  const sidebarTickersKey = [tickers, portfolioTickers, trendingTickers, analyzedTickers]
    .filter(Boolean)
    .flat()
    .join(',')

  useEffect(() => {
    if (!sidebarTickersKey) return
    let cancelled = false
    const symbols = [...new Set(sidebarTickersKey.split(','))]
    getJSON(`/watchlist?symbols=${symbols.join(',')}`)
      .then((data) => {
        if (cancelled) return
        setQuotes(Object.fromEntries(data.map((q) => [q.ticker, q])))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sidebarTickersKey])

  useEffect(() => {
    let cancelled = false
    loadTradingViewScript().then(() => {
      if (cancelled || !containerRef.current) return
      containerRef.current.innerHTML = ''
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      // eslint-disable-next-line no-new
      new window.TradingView.widget({
        autosize: true,
        symbol,
        interval: 'D',
        range: '12M',
        timezone: 'Etc/UTC',
        theme: isDark ? 'dark' : 'light',
        style: '1',
        locale: 'en',
        enable_publishing: false,
        allow_symbol_change: true,
        studies: DEFAULT_STUDIES,
        details: true,
        hotlist: true,
        calendar: true,
        // Compare overlays are a construction-time param on the free widget,
        // not a live JS API call - the widget has to be rebuilt to change them.
        compareSymbols: compareSymbols.map((s) => ({ symbol: s, position: 'SameScale' })),
        container_id: CONTAINER_ID,
      })
    })
    return () => {
      cancelled = true
    }
  }, [symbol, compareSymbols])

  function toggleCompare(compareSymbol) {
    setCompareSymbols((prev) =>
      prev.includes(compareSymbol) ? prev.filter((s) => s !== compareSymbol) : [...prev, compareSymbol],
    )
  }

  function handleSearchSubmit(e) {
    e.preventDefault()
    const value = normalizeSymbol(searchInput)
    if (!value) return
    setSymbol(value)
    setSearchInput('')
  }

  const activeTicker = symbol.split(':').pop()

  return (
    <div className="advanced-charts">
      <aside className="advanced-charts__sidebar card">
        <SidebarSection
          title="Watchlist"
          tickers={tickers}
          emptyMessage="No watchlist tickers yet."
          activeTicker={activeTicker}
          onSelect={setSymbol}
          quotes={quotes}
        />
        <SidebarSection
          title="Portfolio"
          tickers={portfolioTickers}
          emptyMessage="No holdings connected."
          activeTicker={activeTicker}
          onSelect={setSymbol}
          quotes={quotes}
        />
        <SidebarSection
          title="Trending"
          tickers={trendingTickers}
          emptyMessage="No trending data right now."
          activeTicker={activeTicker}
          onSelect={setSymbol}
          quotes={quotes}
        />
        <SidebarSection
          title="Recently Analyzed"
          tickers={analyzedTickers}
          emptyMessage="No Stock Team analyses yet."
          activeTicker={activeTicker}
          onSelect={setSymbol}
          quotes={quotes}
        />
      </aside>

      <div className="advanced-charts__main">
        <div className="advanced-charts__toolbar card">
          <form className="advanced-charts__search" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search symbol (e.g. AAPL, NASDAQ:MSFT)"
              className="advanced-charts__search-input"
            />
            <button type="submit" className="advanced-charts__search-submit">
              Go
            </button>
          </form>
          <div className="advanced-charts__compare">
            <span className="advanced-charts__compare-label">Compare</span>
            {COMPARE_PRESETS.map((p) => (
              <button
                key={p.symbol}
                type="button"
                className={`advanced-charts__compare-btn${compareSymbols.includes(p.symbol) ? ' advanced-charts__compare-btn--active' : ''}`}
                onClick={() => toggleCompare(p.symbol)}
                title={p.label}
              >
                {p.symbol}
              </button>
            ))}
            {compareSymbols.length > 0 && (
              <button
                type="button"
                className="advanced-charts__compare-btn advanced-charts__compare-btn--clear"
                onClick={() => setCompareSymbols([])}
              >
                Clear
              </button>
            )}
          </div>
        </div>

        <div className="card advanced-charts__chart-card">
          <div id={CONTAINER_ID} ref={containerRef} className="advanced-charts__chart" />
        </div>
      </div>
    </div>
  )
}
