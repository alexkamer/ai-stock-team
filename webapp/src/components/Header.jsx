import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './Header.css'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/markets/stocks/most-active', label: 'Markets', activeMatch: '/markets' },
  {
    label: 'Research',
    activeMatch: '/research',
    children: [
      { to: '/research/stock-comparison', label: 'Stock comparison' },
    ],
  },
  { to: '/chat', label: 'Chat', end: true },
  { to: '/brokerage', label: 'Brokerage', end: true },
]

export default function Header() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const { user, isLoading, logout } = useAuth()

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
      <div className="app-header__inner">
        <Link to="/" className="app-header__brand">
          AI Stock Team
        </Link>
        <nav className="app-header__nav">
          {NAV_LINKS.map(({ to, label, end, activeMatch, children }) => {
            const isActive = activeMatch
              ? location.pathname.startsWith(activeMatch)
              : end
                ? location.pathname === to
                : location.pathname.startsWith(to)

            if (children) {
              return (
                <div key={label} className="app-header__nav-item app-header__nav-item--dropdown">
                  <span
                    className={`app-header__nav-link${isActive ? ' app-header__nav-link--active' : ''}`}
                  >
                    {label}
                  </span>
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
              <Link
                key={to}
                to={to}
                className={`app-header__nav-link${isActive ? ' app-header__nav-link--active' : ''}`}
              >
                {label}
              </Link>
            )
          })}
        </nav>
        <form className="app-header__search" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Jump to ticker (e.g. TSLA)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Ticker search"
          />
          <button type="submit">Go</button>
        </form>
        {!isLoading && (
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
    </header>
  )
}
