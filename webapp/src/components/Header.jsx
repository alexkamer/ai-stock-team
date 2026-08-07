import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import './Header.css'

export default function Header() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

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
          <span className="app-header__brand-mark">◆</span>
          AI Stock Team
        </Link>
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
      </div>
    </header>
  )
}
