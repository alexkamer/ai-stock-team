import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { getJSON } from '../api/client'
import { useAuth } from '../context/AuthContext'
import './Header.css'

// Mirrors Dashboard.jsx's MARKET_INSTRUMENTS - chartSymbol is the ETF stand-in
// TradingView's widget resolves, since it doesn't recognize raw index tickers.
const INDEX_INSTRUMENTS = [
  { ticker: '^GSPC', label: 'S&P', chartSymbol: 'SPY' },
  { ticker: '^DJI', label: 'Dow', chartSymbol: 'DIA' },
  { ticker: '^IXIC', label: 'Nasdaq', chartSymbol: 'QQQ' },
]

const NAV_LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/markets/stocks/most-active', label: 'Markets', activeMatch: '/markets' },
  {
    label: 'Research',
    activeMatch: '/research',
    children: [
      { to: '/research/stock-comparison', label: 'Stock comparison' },
      { to: '/research/advanced-charts', label: 'Advanced charts' },
    ],
  },
  { to: '/scan', label: 'Buy Scan', end: true },
  { to: '/themes', label: 'Themes', end: true },
  { to: '/chat', label: 'Chat', end: true },
  { to: '/brokerage', label: 'Brokerage', end: true },
  { to: '/track-record', label: 'Track Record', end: true },
]

const DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

const TIME_FORMAT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
})

function getMarketStatus(now) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  }).formatToParts(now)
  const weekday = parts.find((p) => p.type === 'weekday').value
  const hour = Number(parts.find((p) => p.type === 'hour').value)
  const minute = Number(parts.find((p) => p.type === 'minute').value)
  const minutesSinceMidnight = hour * 60 + minute
  const isWeekday = !['Sat', 'Sun'].includes(weekday)
  const isTradingHours = minutesSinceMidnight >= 9 * 60 + 30 && minutesSinceMidnight < 16 * 60
  return isWeekday && isTradingHours ? 'open' : 'closed'
}

export default function Header() {
  const [query, setQuery] = useState('')
  const [now, setNow] = useState(() => new Date())
  const [indices, setIndices] = useState(null)
  const [navOpen, setNavOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, authRequired, isLoading, logout } = useAuth()

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const symbols = INDEX_INSTRUMENTS.map((i) => i.ticker).join(',')
    function fetchIndices() {
      getJSON(`/watchlist?symbols=${symbols}`)
        .then(setIndices)
        .catch(() => {})
    }
    fetchIndices()
    const id = setInterval(fetchIndices, 60_000)
    return () => clearInterval(id)
  }, [])

  const marketStatus = getMarketStatus(now)

  async function handleLogout() {
    await logout()
    navigate('/')
  }

  function handleSubmit(e) {
    e.preventDefault()
    const ticker = query.trim().toUpperCase()
    if (!ticker) return
    navigate(`/tickers/${ticker}`)
    setQuery('')
  }

  return (
    <header className="app-header">
      <div className="app-header__utility">
        <div className="app-header__utility-inner">
          <span className="app-header__date">
            {DATE_FORMAT.format(now)} &middot; {TIME_FORMAT.format(now)} ET
          </span>
          <span className={`app-header__market app-header__market--${marketStatus}`}>
            <span className="app-header__market-dot" />
            Market {marketStatus}
          </span>
          <div className="app-header__indices">
            {INDEX_INSTRUMENTS.map(({ ticker, label, chartSymbol }) => {
              const q = indices?.find((r) => r.ticker === ticker)
              if (!q) {
                return (
                  <span key={ticker} className="app-header__index">
                    <span>{label}</span>
                    <span className="app-header__index-change--loading" />
                  </span>
                )
              }
              const positive = q.day_change_percent >= 0
              return (
                <Link
                  key={ticker}
                  to={`/research/advanced-charts?symbol=${chartSymbol}`}
                  className="app-header__index"
                >
                  <span>{label}</span>
                  <span
                    className={`num app-header__index-change${positive ? ' app-header__index-change--good' : ' app-header__index-change--bad'}`}
                  >
                    {positive ? '+' : ''}
                    {q.day_change_percent.toFixed(2)}%
                  </span>
                </Link>
              )
            })}
          </div>
          {!isLoading && authRequired && (
            <div className="app-header__account">
              {user ? (
                <>
                  <span className="app-header__account-email">{user.email}</span>
                  <button type="button" onClick={handleLogout}>
                    Log out
                  </button>
                </>
              ) : (
                <>
                  <Link to="/login">Log in</Link>
                  <Link to="/signup">Sign up</Link>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="app-header__masthead">
        <Link to="/" className="app-header__brand">
          AI Stock Team
        </Link>

        <button
          type="button"
          className="app-header__nav-toggle"
          aria-expanded={navOpen}
          aria-label="Toggle navigation"
          onClick={() => setNavOpen((open) => !open)}
        >
          <span />
          <span />
          <span />
        </button>

        <nav className={`app-header__nav${navOpen ? ' app-header__nav--open' : ''}`}>
          {NAV_LINKS.map(({ to, label, end, activeMatch, children }) => {
            const isActive = activeMatch
              ? location.pathname.startsWith(activeMatch)
              : end
                ? location.pathname === to
                : location.pathname.startsWith(to)

            if (children) {
              return (
                <div key={label} className="app-header__nav-item app-header__nav-item--dropdown">
                  <button
                    type="button"
                    className={`app-header__nav-link${isActive ? ' app-header__nav-link--active' : ''}`}
                    aria-haspopup="true"
                  >
                    {label}
                    <span className="app-header__nav-caret" aria-hidden="true">&#9662;</span>
                  </button>
                  <div className="app-header__nav-dropdown">
                    {children.map((child) => (
                      <Link key={child.to} to={child.to} className="app-header__nav-dropdown-link">
                        {child.label}
                      </Link>
                    ))}
                  </div>
                </div>
              )
            }

            return (
              <div key={to} className="app-header__nav-item">
                <Link
                  to={to}
                  className={`app-header__nav-link${isActive ? ' app-header__nav-link--active' : ''}`}
                >
                  {label}
                </Link>
              </div>
            )
          })}
        </nav>

        <form className="app-header__search" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Jump to ticker"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Ticker search"
          />
          <button type="submit" aria-label="Go">
            &rarr;
          </button>
        </form>
      </div>
    </header>
  )
}
