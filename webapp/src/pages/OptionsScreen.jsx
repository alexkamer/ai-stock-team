import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import './StockScreen.css'

// Screens available under /markets/options/:screen - key must match a name
// in the backend's OPTIONS_SCREENS registry (src/core/api.py).
export const OPTIONS_SCREENS = [
  { key: 'most-active', label: 'Most Active' },
  { key: 'highest-open-interest', label: 'Highest Open Interest' },
]

const DEFAULT_SCREEN = OPTIONS_SCREENS[0].key

function ChangeBadge({ percent }) {
  const positive = percent >= 0
  return (
    <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
      {positive ? '+' : '-'}{Math.abs(percent).toFixed(2)}%
    </span>
  )
}

function formatExpiry(ms) {
  if (!ms) return '—'
  return new Date(ms).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export default function OptionsScreen() {
  const { screen = DEFAULT_SCREEN } = useParams()
  const navigate = useNavigate()
  const [contracts, setContracts] = useState(null)
  const [error, setError] = useState(null)

  const active = OPTIONS_SCREENS.find((s) => s.key === screen) ?? OPTIONS_SCREENS[0]

  useEffect(() => {
    let cancelled = false
    setContracts(null)
    setError(null)
    getJSON(`/markets/options/${active.key}?limit=25`)
      .then((data) => !cancelled && setContracts(data))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [active.key])

  if (error) return <div className="error-banner">Failed to load {active.label.toLowerCase()}: {error}</div>

  return (
    <div className="stock-screen">
      <div className="stock-screen__header">
        <span className="eyebrow">Options</span>
        <h1>{active.label}</h1>
      </div>

      <nav className="stock-screen__filters" aria-label="Options screen filter">
        {OPTIONS_SCREENS.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`stock-screen__filter ${s.key === active.key ? 'stock-screen__filter--active' : ''}`}
            onClick={() => navigate(`/markets/options/${s.key}`)}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <div className="card stock-screen__table stock-screen__table--options">
        <div className="stock-screen__table-head stock-screen__table-head--options">
          <span>Contract</span>
          <span>Underlying</span>
          <span className="stock-screen__col-price">Price</span>
          <span className="stock-screen__col-volume">Volume</span>
          <span className="stock-screen__col-volume">Open interest</span>
          <span>Expires</span>
        </div>
        {contracts === null
          ? Array.from({ length: 10 }, (_, i) => <div key={i} className="stock-screen__row stock-screen__row--loading" />)
          : contracts.length === 0
          ? <div className="stock-screen__row stock-screen__row--empty">No data right now.</div>
          : contracts.map((c) => (
              <Link
                key={c.ticker}
                to={`/tickers/${c.underlying_symbol}`}
                className="stock-screen__row stock-screen__row--options"
              >
                <span className="stock-screen__name">
                  <span className="watchlist-row__ticker">{c.company_name}</span>
                  <span className="watchlist-row__company">Strike {c.strike}</span>
                </span>
                <span className="watchlist-row__ticker">{c.underlying_symbol}</span>
                <span className="stock-screen__col-price">
                  <span className="watchlist-row__price num">{c.price.toFixed(2)}</span>
                  <ChangeBadge percent={c.day_change_percent} />
                </span>
                <span className="stock-screen__col-volume num">{c.volume ? c.volume.toLocaleString() : '—'}</span>
                <span className="stock-screen__col-volume num">
                  {c.open_interest ? c.open_interest.toLocaleString() : '—'}
                </span>
                <span className="num">{formatExpiry(c.expire_date)}</span>
              </Link>
            ))}
      </div>
    </div>
  )
}
