import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import Sparkline from '../components/Sparkline'
import './StockScreen.css'

// Screens available under /markets/stocks/:screen - key must match a name in
// the backend's STOCK_SCREENS registry (src/core/api.py). Only stocks for
// now; other asset classes (crypto, ETFs as their own tab, indices, ...)
// are a future filter dimension alongside this one.
export const STOCK_SCREENS = [
  { key: 'most-active', label: 'Most Active' },
  { key: 'gainers', label: 'Top Gainers' },
  { key: 'losers', label: 'Top Losers' },
  { key: 'top-performing', label: 'Top Performing' },
  { key: 'trending', label: 'Trending Now' },
  { key: 'best-historical', label: 'Best Historical Performance' },
  { key: 'top-etfs', label: 'Top ETFs' },
]

const DEFAULT_SCREEN = STOCK_SCREENS[0].key

// sqrt-scaled so both quiet screens (most-active, ~1-3% moves) and volatile
// ones (gainers/losers, 15-35%+ moves) spread across the color range instead
// of everything past ~8% saturating to the same flat color.
function heatmapColor(percent) {
  const magnitude = Math.round(Math.min(Math.sqrt(Math.abs(percent) / 30), 1) * 90)
  const token = percent >= 0 ? '--good' : '--critical'
  return `color-mix(in srgb, var(${token}) ${magnitude}%, var(--surface-1))`
}

// Coordinate space the squarified treemap lays tiles out in - its aspect
// ratio (5:3) must match .stock-screen__heatmap's CSS aspect-ratio, since
// tile positions are expressed as % of this grid.
const TREEMAP_WIDTH = 1000
const TREEMAP_HEIGHT = 600

function worstAspectRatio(row, rowLength) {
  let worst = 0
  for (const item of row) {
    const side = item.area / rowLength
    const ratio = Math.max(rowLength / side, side / rowLength)
    if (ratio > worst) worst = ratio
  }
  return worst
}

// Squarified treemap (Bruls et al.) - packs `items` (pre-sorted descending
// by `value`, each getting an `area` proportional to it) edge-to-edge into
// the x/y/w/h rect, always slicing along whichever side is currently
// shorter so tiles stay closer to square instead of thin slivers.
function squarify(items, x, y, w, h) {
  if (items.length === 0) return []
  const results = []
  let remaining = items
  let rx = x
  let ry = y
  let rw = w
  let rh = h

  while (remaining.length) {
    const shortSide = Math.min(rw, rh)
    let row = [remaining[0]]
    let rowArea = remaining[0].area
    for (let i = 1; i < remaining.length; i++) {
      const next = remaining[i]
      const nextRow = row.concat(next)
      const nextArea = rowArea + next.area
      if (worstAspectRatio(nextRow, nextArea / shortSide) <= worstAspectRatio(row, rowArea / shortSide)) {
        row = nextRow
        rowArea = nextArea
      } else {
        break
      }
    }

    const rowLength = rowArea / shortSide
    if (rw >= rh) {
      let cy = ry
      for (const item of row) {
        const itemHeight = item.area / rowLength
        results.push({ ...item, x: rx, y: cy, w: rowLength, h: itemHeight })
        cy += itemHeight
      }
      rx += rowLength
      rw -= rowLength
    } else {
      let cx = rx
      for (const item of row) {
        const itemWidth = item.area / rowLength
        results.push({ ...item, x: cx, y: ry, w: itemWidth, h: rowLength })
        cx += itemWidth
      }
      ry += rowLength
      rh -= rowLength
    }

    remaining = remaining.slice(row.length)
  }

  return results
}

// Sizes each ticker by cbrt(market cap) where known - dampens outliers (a
// $1T+ mega-cap next to a $2B small-cap) so one tile doesn't swallow the
// whole map while still ranking bigger caps larger. Unknown caps (e.g. the
// trending screen, which has no cap field) fall back to the smallest known
// cap rather than 0, so they still get a visible tile instead of vanishing.
function layoutTreemap(tickers) {
  const caps = tickers.map((t) => t.market_cap).filter((c) => c > 0)
  const fallback = caps.length ? Math.min(...caps) : 1
  const weight = (cap) => Math.cbrt(cap > 0 ? cap : fallback)
  const total = tickers.reduce((sum, t) => sum + weight(t.market_cap), 0)
  const items = tickers
    .map((t) => ({
      ticker: t,
      area: (weight(t.market_cap) / total) * TREEMAP_WIDTH * TREEMAP_HEIGHT,
    }))
    .sort((a, b) => b.area - a.area)
  return squarify(items, 0, 0, TREEMAP_WIDTH, TREEMAP_HEIGHT)
}

// Volume/avg-volume use the same M/B/T compaction as market cap once past
// 1M, but keep the exact count below that threshold, where "0.85M" would
// be less readable than "850,000".
function formatVolume(volume) {
  if (!volume) return '—'
  if (volume >= 1e12) return `${(volume / 1e12).toFixed(2)}T`
  if (volume >= 1e9) return `${(volume / 1e9).toFixed(2)}B`
  if (volume >= 1e6) return `${(volume / 1e6).toFixed(2)}M`
  return Math.round(volume).toLocaleString()
}

function formatMarketCap(cap) {
  if (!cap) return 'N/A'
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(2)}T`
  if (cap >= 1e9) return `$${(cap / 1e9).toFixed(2)}B`
  if (cap >= 1e6) return `$${(cap / 1e6).toFixed(2)}M`
  return `$${cap.toLocaleString()}`
}

// Rough monospace glyph width (this app's --mono font) as a fraction of
// font-size, for estimating whether a label fits a tile's pixel box before
// rendering it - the treemap's coordinate units track real pixels closely
// enough (given .stock-screen__heatmap's fixed 5:3 aspect ratio) to use w/h
// directly here.
const MONO_CHAR_WIDTH_RATIO = 0.62
const TILE_HORIZONTAL_PADDING = 12

function estimateTextWidth(text, fontSize) {
  return text.length * fontSize * MONO_CHAR_WIDTH_RATIO
}

function HeatmapTile({ ticker, x, y, w, h }) {
  const percent = ticker.day_change_percent ?? 0
  const minSide = Math.min(w, h)
  const fontSize = Math.max(9, Math.min(20, minSide / 5.5))
  const availableWidth = w - TILE_HORIZONTAL_PADDING

  const tickerWidth = estimateTextWidth(ticker.ticker, fontSize)
  const showTicker = tickerWidth <= availableWidth && fontSize + 8 <= h

  const percentText = `${percent >= 0 ? '+' : ''}${percent.toFixed(2)}%`
  const percentFontSize = fontSize * 0.8
  const showPercent =
    showTicker &&
    h > fontSize * 2 + 12 &&
    estimateTextWidth(percentText, percentFontSize) <= availableWidth

  return (
    <Link
      to={`/tickers/${ticker.ticker}`}
      className="stock-screen__tile"
      style={{
        left: `${(x / TREEMAP_WIDTH) * 100}%`,
        top: `${(y / TREEMAP_HEIGHT) * 100}%`,
        width: `${(w / TREEMAP_WIDTH) * 100}%`,
        height: `${(h / TREEMAP_HEIGHT) * 100}%`,
        background: heatmapColor(percent),
      }}
    >
      <span className="stock-screen__tile-tooltip">
        <span className="stock-screen__tile-tooltip-ticker">{ticker.ticker}</span>
        <span className="stock-screen__tile-tooltip-row">
          Day: {percent >= 0 ? '+' : ''}{percent.toFixed(2)}%
        </span>
        <span className="stock-screen__tile-tooltip-row">Market cap: {formatMarketCap(ticker.market_cap)}</span>
      </span>
      {showTicker && (
        <span className="stock-screen__tile-inner">
          <span className="stock-screen__tile-ticker" style={{ fontSize }}>{ticker.ticker}</span>
          {showPercent && (
            <span className="stock-screen__tile-percent" style={{ fontSize: percentFontSize }}>
              {percentText}
            </span>
          )}
        </span>
      )}
    </Link>
  )
}

// Backend sends this as "56.01 - 184.0" (yfinance's fiftyTwoWeekRange
// string) rather than separate min/max fields - parsed here into a slider
// so the current price's position within the range is visible at a glance.
function FiftyTwoWeekRange({ range, price }) {
  if (!range) return <span className="num">—</span>
  const [low, high] = range.split(' - ').map(Number)
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return <span className="num">{range}</span>

  const clamped = Math.min(Math.max(price, low), high)
  const positionPercent = ((clamped - low) / (high - low)) * 100

  return (
    <span className="stock-screen__range">
      <span className="stock-screen__range-label num">{low.toFixed(2)}</span>
      <span className="stock-screen__range-track">
        <span className="stock-screen__range-dot" style={{ left: `${positionPercent}%` }} />
      </span>
      <span className="stock-screen__range-label num">{high.toFixed(2)}</span>
    </span>
  )
}

const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100]
const DEFAULT_ROWS_PER_PAGE = 25

// Windowed page-number list (1 ... current-1 current current+1 ... last)
// rather than every page, since some screens' `total` can run into the
// hundreds (e.g. top-performing's ~2000-stock pool) at a small rows-per-page.
function paginationItems(page, pageCount) {
  const items = []
  const add = (p) => items.push(p)
  const addGapIfNeeded = (prev, next) => {
    if (next - prev === 2) add(prev + 1)
    else if (next - prev > 2) items.push('ellipsis')
  }

  add(0)
  let last = 0
  for (let p = Math.max(1, page - 1); p <= Math.min(pageCount - 2, page + 1); p++) {
    addGapIfNeeded(last, p)
    add(p)
    last = p
  }
  if (pageCount > 1) {
    addGapIfNeeded(last, pageCount - 1)
    add(pageCount - 1)
  }
  return items
}

function Pagination({ page, pageCount, rowsPerPage, total, onPageChange }) {
  if (pageCount <= 1) return null
  const rangeStart = page * rowsPerPage + 1
  const rangeEnd = Math.min(total, rangeStart + rowsPerPage - 1)
  return (
    <div className="stock-screen__pagination-bar">
      <span className="stock-screen__pagination-range">
        {rangeStart}–{rangeEnd} of {total.toLocaleString()}
      </span>
      <nav className="stock-screen__pagination" aria-label="Table pagination">
        <button type="button" disabled={page === 0} onClick={() => onPageChange(page - 1)}>
          Prev
        </button>
        {paginationItems(page, pageCount).map((item, i) =>
          item === 'ellipsis' ? (
            <span key={`ellipsis-${i}`} className="stock-screen__pagination-ellipsis">…</span>
          ) : (
            <button
              key={item}
              type="button"
              aria-current={item === page ? 'page' : undefined}
              className={item === page ? 'stock-screen__pagination-page--active' : ''}
              onClick={() => onPageChange(item)}
            >
              {item + 1}
            </button>
          )
        )}
        <button type="button" disabled={page >= pageCount - 1} onClick={() => onPageChange(page + 1)}>
          Next
        </button>
      </nav>
    </div>
  )
}

export default function StockScreen() {
  const { screen = DEFAULT_SCREEN } = useParams()
  const navigate = useNavigate()
  const [tickers, setTickers] = useState(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [view, setView] = useState('table')
  const [rowsPerPage, setRowsPerPage] = useState(DEFAULT_ROWS_PER_PAGE)
  const [page, setPage] = useState(0)

  const active = STOCK_SCREENS.find((s) => s.key === screen) ?? STOCK_SCREENS[0]
  const pageCount = Math.max(1, Math.ceil(total / rowsPerPage))

  useEffect(() => {
    setPage(0)
  }, [active.key, rowsPerPage])

  useEffect(() => {
    let cancelled = false
    setTickers(null)
    setError(null)
    const offset = page * rowsPerPage
    getJSON(`/markets/stocks/${active.key}?limit=${rowsPerPage}&offset=${offset}`)
      .then((data) => {
        if (cancelled) return
        setTickers(data.items)
        setTotal(data.total)
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [active.key, rowsPerPage, page])

  if (error) return <div className="error-banner">Failed to load {active.label.toLowerCase()}: {error}</div>

  return (
    <div className="stock-screen">
      <div className="stock-screen__header">
        <span className="eyebrow">Stocks</span>
        <h1>{active.label}</h1>
      </div>

      <nav className="stock-screen__filters" aria-label="Stock screen filter">
        {STOCK_SCREENS.map((s, i) => (
          <span key={s.key} className="stock-screen__filter-item">
            {i > 0 && <span className="stock-screen__filter-divider" aria-hidden="true">|</span>}
            <button
              type="button"
              className={`stock-screen__filter ${s.key === active.key ? 'stock-screen__filter--active' : ''}`}
              onClick={() => navigate(`/markets/stocks/${s.key}`)}
            >
              {s.label}
            </button>
          </span>
        ))}
      </nav>

      <div className="stock-screen__toolbar">
        <div className="stock-screen__view-toggle" role="group" aria-label="View mode">
          {['table', 'heatmap'].map((mode) => (
            <button
              key={mode}
              type="button"
              className={`stock-screen__view-toggle-btn ${view === mode ? 'stock-screen__view-toggle-btn--active' : ''}`}
              onClick={() => setView(mode)}
            >
              {mode === 'table' ? 'Table' : 'Heatmap'}
            </button>
          ))}
        </div>

        <label className="stock-screen__rows-per-page">
          Rows per page
          <select value={rowsPerPage} onChange={(e) => setRowsPerPage(Number(e.target.value))}>
            {ROWS_PER_PAGE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>

      {view === 'table' ? (
        <div className="card stock-screen__table stock-screen__table--full">
          <div className="stock-screen__table-head stock-screen__table-head--full">
            <span>Symbol</span>
            <span>Name</span>
            <span className="stock-screen__col-num">Price</span>
            <span className="stock-screen__col-num">Change</span>
            <span className="stock-screen__col-num">Change %</span>
            <span className="stock-screen__col-num">Volume</span>
            <span className="stock-screen__col-num">Avg Vol (3M)</span>
            <span className="stock-screen__col-num">Market Cap</span>
            <span className="stock-screen__col-num">P/E Ratio (TTM)</span>
            <span className="stock-screen__col-num">52 Wk Change %</span>
            <span className="stock-screen__col-num">52 Wk Range</span>
          </div>
          {tickers === null
            ? Array.from({ length: 10 }, (_, i) => <div key={i} className="stock-screen__row stock-screen__row--loading" />)
            : tickers.length === 0
            ? <div className="stock-screen__row stock-screen__row--empty">No data right now.</div>
            : tickers.map((t) => {
                const changePositive = t.day_change_percent >= 0
                const fiftyTwoWkPositive = (t.fifty_two_week_change_percent ?? 0) >= 0
                return (
                  <Link key={t.ticker} to={`/tickers/${t.ticker}`} className="stock-screen__row stock-screen__row--full">
                    <span className="watchlist-row__ticker">{t.ticker}</span>
                    <span className="watchlist-row__company">
                      <span className="watchlist-row__company-name">{t.company_name}</span>
                      <Sparkline values={t.day_prices} width={64} height={24} positive={changePositive} />
                    </span>
                    <span className="stock-screen__col-num stock-screen__col-price num">
                      ${t.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                    <span className={`stock-screen__col-num num ${changePositive ? 'text-good' : 'text-critical'}`}>
                      {t.day_change_abs != null
                        ? `${changePositive ? '+' : ''}${t.day_change_abs.toFixed(2)}`
                        : '—'}
                    </span>
                    <span className={`stock-screen__col-num num ${changePositive ? 'text-good' : 'text-critical'}`}>
                      {changePositive ? '+' : ''}{t.day_change_percent.toFixed(2)}%
                    </span>
                    <span className="stock-screen__col-num num">{formatVolume(t.volume)}</span>
                    <span className="stock-screen__col-num num">{formatVolume(t.avg_volume_3m)}</span>
                    <span className="stock-screen__col-num num">{formatMarketCap(t.market_cap)}</span>
                    <span className="stock-screen__col-num num">
                      {t.pe_ratio_ttm != null ? t.pe_ratio_ttm.toFixed(2) : '—'}
                    </span>
                    <span
                      className={`stock-screen__col-num num ${
                        t.fifty_two_week_change_percent != null ? (fiftyTwoWkPositive ? 'text-good' : 'text-critical') : ''
                      }`}
                    >
                      {t.fifty_two_week_change_percent != null
                        ? `${fiftyTwoWkPositive ? '+' : ''}${t.fifty_two_week_change_percent.toFixed(2)}%`
                        : '—'}
                    </span>
                    <span className="stock-screen__col-num">
                      <FiftyTwoWeekRange range={t.fifty_two_week_range} price={t.price} />
                    </span>
                  </Link>
                )
              })}
        </div>
      ) : (
        <div className="stock-screen__heatmap">
          {tickers === null ? (
            <div className="stock-screen__tile stock-screen__tile--loading" style={{ left: 0, top: 0, width: '100%', height: '100%' }} />
          ) : tickers.length === 0 ? (
            <div className="stock-screen__row--empty">No data right now.</div>
          ) : (
            layoutTreemap(tickers).map((tile) => (
              <HeatmapTile key={tile.ticker.ticker} ticker={tile.ticker} x={tile.x} y={tile.y} w={tile.w} h={tile.h} />
            ))
          )}
        </div>
      )}

      <Pagination page={page} pageCount={pageCount} rowsPerPage={rowsPerPage} total={total} onPageChange={setPage} />
    </div>
  )
}
