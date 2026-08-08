import { useEffect, useState } from 'react'
import { getJSON } from '../api/client'
import './StockScreen.css'

// Only one screen for this asset class - Yahoo's predefined screener only
// exposes a "highest valuation" ranking for private companies, so there's no
// filter bar to switch between (unlike stocks/options). Matches the backend's
// PRIVATE_COMPANY_SCREENS registry key (src/core/api.py).
const SCREEN_LABEL = 'Highest Valuation'

function ChangeBadge({ percent }) {
  const positive = percent >= 0
  return (
    <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
      {positive ? '+' : '-'}{Math.abs(percent).toFixed(2)}%
    </span>
  )
}

function formatBillions(value) {
  if (value == null) return '—'
  return `$${(value / 1e9).toFixed(1)}B`
}

export default function PrivateCompaniesScreen() {
  const [companies, setCompanies] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getJSON('/markets/private-companies/highest-valuation?limit=25')
      .then((data) => !cancelled && setCompanies(data))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <div className="error-banner">Failed to load private companies: {error}</div>

  return (
    <div className="stock-screen">
      <div className="stock-screen__header">
        <span className="eyebrow">Private Companies</span>
        <h1>{SCREEN_LABEL}</h1>
      </div>

      <div className="card stock-screen__table stock-screen__table--private">
        <div className="stock-screen__table-head stock-screen__table-head--private">
          <span>Company</span>
          <span>Sector</span>
          <span className="stock-screen__col-price">Est. valuation</span>
          <span className="stock-screen__col-volume">52wk change</span>
          <span className="stock-screen__col-volume">Funding to date</span>
        </div>
        {companies === null
          ? Array.from({ length: 10 }, (_, i) => <div key={i} className="stock-screen__row stock-screen__row--loading" />)
          : companies.length === 0
          ? <div className="stock-screen__row stock-screen__row--empty">No data right now.</div>
          : companies.map((c) => (
              <div key={c.ticker} className="stock-screen__row stock-screen__row--private">
                <span className="stock-screen__name">
                  <span className="watchlist-row__ticker">{c.company_name}</span>
                  <span className="watchlist-row__company">{c.latest_share_class ?? '—'}</span>
                </span>
                <span className="watchlist-row__company">{c.sector ?? '—'}</span>
                <span className="stock-screen__col-price">
                  <span className="watchlist-row__price num">{formatBillions(c.implied_valuation)}</span>
                </span>
                <span className="stock-screen__col-volume">
                  {c.fifty_two_week_change_percent != null ? (
                    <ChangeBadge percent={c.fifty_two_week_change_percent} />
                  ) : (
                    '—'
                  )}
                </span>
                <span className="stock-screen__col-volume num">{formatBillions(c.funding_to_date)}</span>
              </div>
            ))}
      </div>
    </div>
  )
}
