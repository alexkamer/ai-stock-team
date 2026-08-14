import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useWatchlist } from '../context/WatchlistContext'
import './AdvancedCharts.css'

const TV_SCRIPT_SRC = 'https://s3.tradingview.com/tv.js'
const CONTAINER_ID = 'advanced-charts-tv-container'
const DEFAULT_SYMBOL = 'NASDAQ:AAPL'
const STORAGE_KEY = 'advanced-charts-symbol'

function normalizeSymbol(value) {
  const trimmed = value.trim().toUpperCase()
  if (!trimmed) return null
  return trimmed.includes(':') ? trimmed : `NASDAQ:${trimmed}`
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

export default function AdvancedCharts() {
  const { tickers } = useWatchlist()
  const [searchParams, setSearchParams] = useSearchParams()
  const [symbol, setSymbolState] = useState(
    () =>
      normalizeSymbol(searchParams.get('symbol') ?? '') ??
      loadPersistedSymbol() ??
      (tickers[0] ? `NASDAQ:${tickers[0]}` : DEFAULT_SYMBOL),
  )
  const [searchInput, setSearchInput] = useState('')
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
    loadTradingViewScript().then(() => {
      if (cancelled || !containerRef.current) return
      containerRef.current.innerHTML = ''
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      // eslint-disable-next-line no-new
      new window.TradingView.widget({
        autosize: true,
        symbol,
        interval: 'D',
        timezone: 'Etc/UTC',
        theme: isDark ? 'dark' : 'light',
        style: '1',
        locale: 'en',
        enable_publishing: false,
        allow_symbol_change: true,
        container_id: CONTAINER_ID,
      })
    })
    return () => {
      cancelled = true
    }
  }, [symbol])

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
        <h3 className="advanced-charts__sidebar-title">Watchlist</h3>
        {tickers.length === 0 ? (
          <p className="advanced-charts__sidebar-empty">No watchlist tickers yet.</p>
        ) : (
          <ul className="advanced-charts__watchlist">
            {tickers.map((t) => (
              <li key={t}>
                <button
                  type="button"
                  className={`advanced-charts__watchlist-item${t === activeTicker ? ' advanced-charts__watchlist-item--active' : ''}`}
                  onClick={() => setSymbol(`NASDAQ:${t}`)}
                >
                  {t}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="advanced-charts__main">
        <form className="advanced-charts__search card" onSubmit={handleSearchSubmit}>
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

        <div className="card advanced-charts__chart-card">
          <div id={CONTAINER_ID} ref={containerRef} className="advanced-charts__chart" />
        </div>
      </div>
    </div>
  )
}
