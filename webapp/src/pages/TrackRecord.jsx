import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import { trackRecordCache } from '../api/trackRecordCache'
import './TrackRecord.css'

const VERDICT_LABEL = { buy: 'Buy', hold: 'Hold', sell: 'Sell' }
const HORIZON_LABEL = { '1w': '1 week', '1mo': '1 month', '3mo': '3 months' }
const HORIZONS = [
  { key: '1w', label: '1 week' },
  { key: '1mo', label: '1 month' },
  { key: '3mo', label: '3 months' },
]

function VerdictBadge({ verdict }) {
  return <span className={`track-record__verdict-badge track-record__verdict-badge--${verdict}`}>{VERDICT_LABEL[verdict]}</span>
}

function AlphaCell({ scored }) {
  if (!scored || scored.status === 'pending') {
    return <span className="track-record__cell track-record__cell--muted">Pending</span>
  }
  if (scored.status === 'unavailable') {
    return <span className="track-record__cell track-record__cell--muted">—</span>
  }
  const positive = scored.alpha_percent >= 0
  return (
    <span className={`track-record__cell track-record__alpha ${scored.hit ? 'track-record__alpha--hit' : 'track-record__alpha--miss'}`}>
      {positive ? '+' : ''}{scored.alpha_percent.toFixed(1)}%
      <span className="track-record__alpha-tag">{scored.hit ? 'Hit' : 'Miss'}</span>
    </span>
  )
}

function PriceTargetCell({ target }) {
  if (!target) return <span className="track-record__cell track-record__cell--muted">—</span>

  const horizonLabel = HORIZON_LABEL[target.horizon] ?? target.horizon

  if (target.status === 'pending') {
    return (
      <span className="track-record__cell track-record__cell--muted">
        ${target.predicted_price.toFixed(2)} by {horizonLabel}
      </span>
    )
  }
  if (target.status === 'unavailable') {
    return <span className="track-record__cell track-record__cell--muted">—</span>
  }
  const over = target.percent_diff >= 0
  return (
    <span className="track-record__cell track-record__target">
      ${target.predicted_price.toFixed(2)} → ${target.actual_price.toFixed(2)}
      <span className={`track-record__target-diff ${over ? 'track-record__target-diff--over' : 'track-record__target-diff--under'}`}>
        {over ? '+' : ''}{target.percent_diff.toFixed(1)}%
      </span>
    </span>
  )
}

function StatTile({ label, value, sub }) {
  return (
    <div className="card track-record__stat">
      <span className="track-record__stat-label">{label}</span>
      <span className="track-record__stat-value">{value}</span>
      {sub && <span className="track-record__stat-sub">{sub}</span>}
    </div>
  )
}

export default function TrackRecord({ ticker, compact = false }) {
  const cacheKey = ticker ?? 'all'
  const [data, setData] = useState(() => trackRecordCache.byKey[cacheKey] ?? null)
  const [error, setError] = useState(null)
  const [sortDir, setSortDir] = useState('desc')

  useEffect(() => {
    setData(trackRecordCache.byKey[cacheKey] ?? null)
    setError(null)
    const path = ticker ? `/track-record?ticker=${ticker}` : '/track-record'
    getJSON(path)
      .then((result) => {
        trackRecordCache.byKey[cacheKey] = result
        setData(result)
      })
      .catch((e) => setError(e.message))
  }, [ticker, cacheKey])

  if (error) return <div className="error-banner">{error}</div>
  if (!data) {
    return (
      <div className={compact ? 'track-record--compact' : 'track-record'}>
        <div className="track-record__pending">Loading track record…</div>
      </div>
    )
  }

  const { stats } = data
  const records = [...data.records].sort((a, b) =>
    sortDir === 'desc' ? b.call_date.localeCompare(a.call_date) : a.call_date.localeCompare(b.call_date)
  )

  if (records.length === 0) {
    return (
      <div className={compact ? 'track-record--compact' : 'track-record'}>
        <p className="track-record__empty">
          {ticker
            ? `No logged verdicts for ${ticker} yet - run Team Analysis to start one.`
            : 'No verdicts logged yet - run Team Analysis on a ticker to start building a track record.'}
        </p>
      </div>
    )
  }

  return (
    <div className={compact ? 'track-record--compact' : 'track-record'}>
      {!compact && (
        <div className="track-record__stats">
          <StatTile label="Calls logged" value={stats.total_calls} />
          <StatTile
            label="Hit rate"
            value={stats.hit_rate_percent != null ? `${stats.hit_rate_percent.toFixed(0)}%` : '—'}
            sub={`${stats.scored_calls} scored`}
          />
          <StatTile
            label="Avg alpha (buy)"
            value={stats.avg_alpha_by_verdict.buy != null ? `${stats.avg_alpha_by_verdict.buy.toFixed(1)}%` : '—'}
          />
          <StatTile
            label="Avg alpha (sell)"
            value={stats.avg_alpha_by_verdict.sell != null ? `${stats.avg_alpha_by_verdict.sell.toFixed(1)}%` : '—'}
          />
        </div>
      )}

      <div className="card track-record__table-card">
        <table className="track-record__table">
          <thead>
            <tr>
              {!ticker && <th>Ticker</th>}
              <th
                className="sortable"
                onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
              >
                Call date
                <span className="track-record__sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
              </th>
              <th>Verdict</th>
              <th className="num">Price at call</th>
              <th>Target</th>
              <th>Since call</th>
              {HORIZONS.map((h) => (
                <th key={h.key}>{h.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                {!ticker && (
                  <td>
                    <Link to={`/tickers/${record.ticker}/team`}>{record.ticker}</Link>
                  </td>
                )}
                <td>{record.call_date}</td>
                <td>
                  <VerdictBadge verdict={record.verdict} />
                </td>
                <td className="num">{record.price_at_call.toFixed(2)}</td>
                <td>
                  <PriceTargetCell target={record.price_target} />
                </td>
                <td>
                  <AlphaCell scored={record.current} />
                </td>
                {HORIZONS.map((h) => (
                  <td key={h.key}>
                    <AlphaCell scored={record.horizons[h.key]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
