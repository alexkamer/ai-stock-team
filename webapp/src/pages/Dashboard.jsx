import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import Sparkline from '../components/Sparkline'
import './Dashboard.css'

const MARKET_INSTRUMENTS = [
  { ticker: '^GSPC', label: 'S&P 500' },
  { ticker: '^DJI', label: 'Dow 30' },
  { ticker: '^IXIC', label: 'Nasdaq' },
  { ticker: '^RUT', label: 'Russell 2000' },
  { ticker: '^VIX', label: 'VIX' },
  { ticker: 'GC=F', label: 'Gold' },
  { ticker: 'BTC-USD', label: 'Bitcoin USD' },
  { ticker: 'CL=F', label: 'Crude Oil' },
]

function ChangeBadge({ percent }) {
  const positive = percent >= 0
  return (
    <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
      {positive ? '↑' : '↓'} {Math.abs(percent).toFixed(2)}%
    </span>
  )
}

export default function Dashboard() {
  const [quotes, setQuotes] = useState(null)
  const [marketQuotesList, setMarketQuotesList] = useState(null)
  const [error, setError] = useState(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const trackRef = useRef(null)

  function updateScrollState() {
    const el = trackRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 4)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4)
  }

  function scrollByAmount(direction) {
    trackRef.current?.scrollBy({ left: direction * 320, behavior: 'smooth' })
  }

  useEffect(() => {
    let cancelled = false
    getJSON('/watchlist')
      .then((data) => !cancelled && setQuotes(data))
      .catch((e) => !cancelled && setError(e.message))
    getJSON(`/watchlist?symbols=${MARKET_INSTRUMENTS.map((i) => i.ticker).join(',')}`)
      .then((data) => !cancelled && setMarketQuotesList(data))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    updateScrollState()
    window.addEventListener('resize', updateScrollState)
    return () => window.removeEventListener('resize', updateScrollState)
  }, [marketQuotesList])

  const byTicker = (list) => Object.fromEntries((list ?? []).map((q) => [q.ticker, q]))
  const marketQuotes = byTicker(marketQuotesList)

  if (error) return <div className="error-banner">Failed to load watchlist: {error}</div>

  return (
    <div className="dashboard">
      <section className="market-strip">
        <div className="market-strip__track" ref={trackRef} onScroll={updateScrollState}>
          {MARKET_INSTRUMENTS.map(({ ticker, label }) => {
            const q = marketQuotes[ticker]
            const positive = (q?.day_change_percent ?? 0) >= 0
            return (
              <div key={ticker} className="market-strip__item">
                <span className="market-strip__label">{label}</span>
                {q ? (
                  <>
                    <span className="market-strip__price num">
                      {q.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </span>
                    <span className={`market-strip__change num ${positive ? 'market-strip__change--good' : 'market-strip__change--bad'}`}>
                      {positive ? '+' : ''}
                      {q.day_change_percent.toFixed(2)}%
                    </span>
                  </>
                ) : (
                  <span className="market-strip__price market-strip__price--loading" />
                )}
              </div>
            )
          })}
        </div>
        <div className="market-strip__nav-group">
          <button
            type="button"
            className="market-strip__nav market-strip__nav--left"
            aria-label="Scroll markets left"
            disabled={!canScrollLeft}
            onClick={() => scrollByAmount(-1)}
          >
            ‹
          </button>
          <button
            type="button"
            className="market-strip__nav market-strip__nav--right"
            aria-label="Scroll markets right"
            disabled={!canScrollRight}
            onClick={() => scrollByAmount(1)}
          >
            ›
          </button>
        </div>
      </section>

      <section className="dashboard__section">
        <div className="dashboard__section-head">
          <h2>Watchlist</h2>
          <span className="dashboard__section-count num">{quotes?.length ?? '–'} tickers</span>
        </div>
        <div className="card watchlist-table">
          <div className="watchlist-table__head">
            <span>Symbol</span>
            <span className="watchlist-table__col-price">Price</span>
            <span className="watchlist-table__col-change">Change</span>
            <span className="watchlist-table__col-chart">1M</span>
          </div>
          {quotes === null
            ? Array.from({ length: 5 }, (_, i) => <div key={i} className="watchlist-row watchlist-row--loading" />)
            : quotes.map((q) => {
                const positive = q.day_change_percent >= 0
                return (
                  <Link key={q.ticker} to={`/tickers/${q.ticker}`} className="watchlist-row">
                    <span className="watchlist-row__name">
                      <span className="watchlist-row__ticker">{q.ticker}</span>
                      <span className="watchlist-row__company">{q.company_name}</span>
                    </span>
                    <span className="watchlist-table__col-price num">${q.price.toFixed(2)}</span>
                    <span className="watchlist-table__col-change">
                      <ChangeBadge percent={q.day_change_percent} />
                    </span>
                    <span className="watchlist-table__col-chart">
                      <Sparkline values={q.sparkline} positive={positive} />
                    </span>
                  </Link>
                )
              })}
          <div className="watchlist-row watchlist-row--add" title="Coming soon">
            <span>+ Add ticker</span>
          </div>
        </div>
      </section>

      <section className="quick-nav">
        <Link to="/tickers/NVDA/team" className="card quick-nav__card">
          <span className="eyebrow">Multi-agent verdict</span>
          <h3>Stock Team Analysis</h3>
          <p>Get a buy/hold/sell verdict from fundamentals + sentiment specialists.</p>
        </Link>
        <Link to="/chat" className="card quick-nav__card">
          <span className="eyebrow">Ask anything</span>
          <h3>Research Chat</h3>
          <p>Ask open-ended questions about your watchlist or any ticker.</p>
        </Link>
      </section>
    </div>
  )
}
