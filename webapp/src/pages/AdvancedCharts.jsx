import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import RangeBar from '../components/RangeBar'
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

// TradingView's free widget takes "range" (the visible window) and
// "interval" (candle resolution) as separate construction-time params -
// each preset pairs a sensible resolution to its window so 1D shows 5-minute
// candles instead of the same daily bars as the 5Y view.
const RANGE_PRESETS = [
  { key: '1D', label: '1D', range: '1D', interval: '5' },
  { key: '5D', label: '5D', range: '5D', interval: '15' },
  { key: '1M', label: '1M', range: '1M', interval: '60' },
  { key: '6M', label: '6M', range: '6M', interval: 'D' },
  { key: 'YTD', label: 'YTD', range: 'YTD', interval: 'D' },
  { key: '1Y', label: '1Y', range: '12M', interval: 'D' },
  { key: '5Y', label: '5Y', range: '60M', interval: 'W' },
]
const DEFAULT_RANGE_KEY = '1Y'
const RANGE_STORAGE_KEY = 'advanced-charts-range'

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

function loadPersistedRangeKey() {
  try {
    return localStorage.getItem(RANGE_STORAGE_KEY)
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

// yfinance's averageAnalystRating comes as a string like "2.1 - Buy" - split
// it into the numeric score (for the gauge) and label (for the badge).
function parseRating(rating) {
  const match = rating?.match(/^([\d.]+)\s*-\s*(.+)$/)
  return match ? { score: parseFloat(match[1]), label: match[2] } : null
}

function ratingTone(score) {
  if (score <= 2.5) return 'good'
  if (score >= 3.5) return 'bad'
  return 'neutral'
}

// A 1 (Strong Buy) to 5 (Strong Sell) gauge, mirroring RangeBar's marker-on-
// a-track shape so the whole panel reads as one family of gauges rather than
// a one-off.
function RatingGauge({ score }) {
  const pct = Math.max(0, Math.min(100, ((score - 1) / 4) * 100))
  return (
    <div className="advanced-charts__rating-gauge">
      <div className="advanced-charts__rating-track">
        <div className="advanced-charts__rating-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="advanced-charts__rating-scale">
        <span>Strong Buy</span>
        <span>Strong Sell</span>
      </div>
    </div>
  )
}

// Collapses the 5-way Strong Buy..Strong Sell breakdown down to the same
// buy/hold/sell vocabulary used everywhere else in the app (track record
// verdicts, etc.) instead of introducing a new 5-color scale.
function RecommendationTrendBar({ trend }) {
  const buy = trend.strong_buy + trend.buy
  const hold = trend.hold
  const sell = trend.sell + trend.strong_sell
  const total = buy + hold + sell
  if (total === 0) return null
  const pct = (n) => Math.round((n / total) * 100)
  return (
    <div className="advanced-charts__rec-trend">
      <div className="advanced-charts__rec-trend-bar">
        {buy > 0 && (
          <div
            className="advanced-charts__rec-trend-seg advanced-charts__rec-trend-seg--buy"
            style={{ width: `${pct(buy)}%` }}
          />
        )}
        {hold > 0 && (
          <div
            className="advanced-charts__rec-trend-seg advanced-charts__rec-trend-seg--hold"
            style={{ width: `${pct(hold)}%` }}
          />
        )}
        {sell > 0 && (
          <div
            className="advanced-charts__rec-trend-seg advanced-charts__rec-trend-seg--sell"
            style={{ width: `${pct(sell)}%` }}
          />
        )}
      </div>
      <div className="advanced-charts__rec-trend-legend">
        <span className="advanced-charts__rec-trend-legend-item advanced-charts__rec-trend-legend-item--buy">
          Buy {pct(buy)}%
        </span>
        <span className="advanced-charts__rec-trend-legend-item">Hold {pct(hold)}%</span>
        <span className="advanced-charts__rec-trend-legend-item advanced-charts__rec-trend-legend-item--sell">
          Sell {pct(sell)}%
        </span>
      </div>
    </div>
  )
}

const ACTION_LABEL = { up: 'Upgrade', down: 'Downgrade', main: 'Maintain', reit: 'Reiterate', init: 'Initiate' }

function ActionBadge({ action }) {
  const tone = action === 'up' ? 'good' : action === 'down' ? 'bad' : 'neutral'
  const arrow = action === 'up' ? '↑' : action === 'down' ? '↓' : ''
  return (
    <span className={`advanced-charts__action-badge advanced-charts__action-badge--${tone}`}>
      {arrow} {ACTION_LABEL[action] ?? action}
    </span>
  )
}

function AnalystPanel({ ticker, price, ratings }) {
  const parsedRating = ratings ? parseRating(ratings.rating) : null

  return (
    <aside className="advanced-charts__research card">
      <h3 className="advanced-charts__sidebar-title">Analyst Ratings</h3>
      {ratings === undefined ? (
        <p className="advanced-charts__sidebar-empty">Loading…</p>
      ) : ratings === null ? (
        <p className="advanced-charts__sidebar-empty">No analyst coverage for {ticker}.</p>
      ) : (
        <>
          <div className="advanced-charts__research-block">
            <span className="advanced-charts__research-label">Consensus</span>
            {parsedRating ? (
              <>
                <div className="advanced-charts__consensus-row">
                  <span className="advanced-charts__consensus-score num">{parsedRating.score.toFixed(1)}</span>
                  <span
                    className={`advanced-charts__rating-badge advanced-charts__rating-badge--${ratingTone(parsedRating.score)}`}
                  >
                    {parsedRating.label}
                  </span>
                </div>
                <RatingGauge score={parsedRating.score} />
              </>
            ) : (
              <span className="advanced-charts__research-value">{ratings.rating ?? '—'}</span>
            )}
            {ratings.analyst_count ? (
              <span className="advanced-charts__research-caption">{ratings.analyst_count} analysts</span>
            ) : null}
          </div>

          {ratings.target_low != null && ratings.target_high != null && price != null && (
            <div className="advanced-charts__research-block">
              <span className="advanced-charts__research-label">Price target</span>
              <RangeBar
                low={ratings.target_low}
                high={ratings.target_high}
                value={price}
                secondaryValue={ratings.target_mean}
                secondaryLabel={`Mean target ${ratings.target_mean?.toFixed(0)}`}
              />
            </div>
          )}

          {ratings.recommendation_trend && (
            <div className="advanced-charts__research-block">
              <span className="advanced-charts__research-label">Recommendation trend</span>
              <RecommendationTrendBar trend={ratings.recommendation_trend} />
            </div>
          )}

          {ratings.recent_changes.length > 0 && (
            <div className="advanced-charts__research-block">
              <span className="advanced-charts__research-label">Recent changes</span>
              <ul className="advanced-charts__rec-changes">
                {ratings.recent_changes.map((c, i) => (
                  <li key={i} className="advanced-charts__rec-change">
                    <div className="advanced-charts__rec-change-top">
                      <span className="advanced-charts__rec-change-firm">{c.firm}</span>
                      <ActionBadge action={c.action} />
                    </div>
                    <div className="advanced-charts__rec-change-bottom">
                      <span className="advanced-charts__rec-change-grade">
                        {c.from_grade && c.from_grade !== c.to_grade ? `${c.from_grade} → ` : ''}
                        {c.to_grade}
                      </span>
                      <span className="advanced-charts__rec-change-date num">{c.date}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </aside>
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
  const [rangeKey, setRangeKeyState] = useState(() => loadPersistedRangeKey() ?? DEFAULT_RANGE_KEY)
  const [analystRatings, setAnalystRatings] = useState(undefined)
  const containerRef = useRef(null)
  const activeTicker = symbol.split(':').pop()

  function setSymbol(next) {
    setSymbolState(next)
    setSearchParams({ symbol: next }, { replace: true })
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage unavailable (private browsing, quota) - just won't persist
    }
  }

  function setRangeKey(next) {
    setRangeKeyState(next)
    try {
      localStorage.setItem(RANGE_STORAGE_KEY, next)
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

  const sidebarTickersKey = [tickers, portfolioTickers, trendingTickers, analyzedTickers, [activeTicker]]
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
    setAnalystRatings(undefined)
    getJSON(`/tickers/${activeTicker}/analyst-ratings`)
      .then((data) => {
        if (cancelled) return
        const hasCoverage = data.rating != null || data.recommendation_trend != null || data.recent_changes.length > 0
        setAnalystRatings(hasCoverage ? data : null)
      })
      .catch(() => !cancelled && setAnalystRatings(null))
    return () => {
      cancelled = true
    }
  }, [activeTicker])

  const activeRangePreset = RANGE_PRESETS.find((p) => p.key === rangeKey) ?? RANGE_PRESETS[0]

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
        interval: activeRangePreset.interval,
        range: activeRangePreset.range,
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
  }, [symbol, compareSymbols, activeRangePreset])

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
          <div className="advanced-charts__range">
            {RANGE_PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`advanced-charts__range-btn${p.key === rangeKey ? ' advanced-charts__range-btn--active' : ''}`}
                onClick={() => setRangeKey(p.key)}
              >
                {p.label}
              </button>
            ))}
          </div>
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

      <AnalystPanel ticker={activeTicker} price={quotes[activeTicker]?.price} ratings={analystRatings} />
    </div>
  )
}
