import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import Sparkline from './Sparkline'
import './CanvasTickerCard.css'

function formatCompact(n) {
  if (n == null) return null
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

function signedPct(n) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function signedAbs(n) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}

/**
 * One growing tile per ticker mentioned in the conversation. Always shows a
 * baseline (name, price, day change) once it loads, regardless of what was
 * asked, so the card is never just a lone P/E ratio with no anchor - and
 * every percent is shown paired with the dollar amount it's a percent of,
 * never on its own.
 */
export default function CanvasTickerCard({ data, selected, onToggleSelect }) {
  const { ticker, companyName, price, dayChangePercent, dayChangeAbs, dayPrices, marketCap, peRatio, history } = data
  const good = dayChangePercent != null && dayChangePercent >= 0
  const [sparkline, setSparkline] = useState(null)

  // The chat agent's get_price_history tool only returns a start/end/high/low
  // summary (for the model to reason over) - once we know a period was
  // asked about, fetch the real per-point series from the same REST route
  // TickerDetail's chart uses, so the sparkline is real data, not a 2-point
  // guess drawn from the summary.
  useEffect(() => {
    if (!history?.period) return
    let cancelled = false
    getJSON(`/tickers/${ticker}/history?period=${history.period}`)
      .then((data) => {
        if (!cancelled) setSparkline(data.prices)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [ticker, history?.period])

  const chartValues = sparkline?.length > 1 ? sparkline : dayPrices?.length > 1 ? dayPrices : null
  const chartPositive = sparkline?.length > 1 ? history.percent_change >= 0 : good
  const chartLabel = sparkline?.length > 1 ? history.period : 'Today'

  return (
    <Link to={`/tickers/${ticker}`} className={`canvas-card${selected ? ' canvas-card--selected' : ''}`}>
      <div className="canvas-card__header">
        <div>
          <span className="canvas-card__ticker">{ticker}</span>
          {companyName && <span className="canvas-card__name">{companyName}</span>}
        </div>
        {onToggleSelect && (
          <label className="canvas-card__compare" onClick={(e) => e.stopPropagation()} title="Compare">
            <input type="checkbox" checked={selected} onChange={() => onToggleSelect(ticker)} />
            Compare
          </label>
        )}
      </div>

      {price != null && (
        <div className="canvas-card__price-row">
          <span className="canvas-card__price num">{price.toFixed(2)}</span>
          {dayChangePercent != null && dayChangeAbs != null && (
            <span className={`canvas-card__delta num${good ? ' canvas-card__delta--good' : ' canvas-card__delta--bad'}`}>
              {signedAbs(dayChangeAbs)} ({signedPct(dayChangePercent)})
            </span>
          )}
        </div>
      )}

      {chartValues && (
        <div className="canvas-card__chart">
          <Sparkline values={chartValues} positive={chartPositive} />
          <span className="canvas-card__chart-label">{chartLabel}</span>
        </div>
      )}

      {(marketCap != null || peRatio != null || (history != null && sparkline)) && (
        <div className="canvas-card__stats">
          {marketCap != null && (
            <span className="canvas-card__stat">
              <span className="canvas-card__stat-label">Mkt cap</span>
              <span className="num">${formatCompact(marketCap)}</span>
            </span>
          )}
          {peRatio != null && (
            <span className="canvas-card__stat">
              <span className="canvas-card__stat-label">P/E</span>
              <span className="num">{peRatio.toFixed(1)}</span>
            </span>
          )}
          {history != null && sparkline && (
            <span className="canvas-card__stat">
              <span className="canvas-card__stat-label">{history.period} change</span>
              <span className={`num${history.percent_change >= 0 ? ' canvas-card__delta--good' : ' canvas-card__delta--bad'}`}>
                {signedPct(history.percent_change)}
              </span>
            </span>
          )}
        </div>
      )}
    </Link>
  )
}
