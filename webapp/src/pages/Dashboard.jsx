import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import NewsFeed from '../components/NewsFeed'
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
      {positive ? '+' : '-'}{Math.abs(percent).toFixed(2)}%
    </span>
  )
}

/** One labeled group of ticker rows inside a shared card - used for
 * Trending, Most Active, Top Gainers, and Top Losers, which share a row
 * shape but come from different feeds. */
function TickerGroup({ label, tickers, emptyMessage, children }) {
  return (
    <div className="ticker-group">
      <span className="ticker-group__label">{label}</span>
      {tickers === null
        ? Array.from({ length: 3 }, (_, i) => <div key={i} className="watchlist-row watchlist-row--loading" />)
        : tickers.length === 0
        ? <div className="watchlist-row watchlist-row--empty">{emptyMessage}</div>
        : tickers.map((t) => {
            const positive = t.day_change_percent >= 0
            return (
              <Link key={t.ticker} to={`/tickers/${t.ticker}`} className="watchlist-row">
                <span className="watchlist-row__name">
                  <span className="watchlist-row__ticker">{t.ticker}</span>
                  <span className="watchlist-row__company">{t.company_name}</span>
                </span>
                <span className="watchlist-table__col-chart">
                  <Sparkline values={t.day_prices} width={64} height={28} positive={positive} />
                </span>
                <span className="watchlist-table__col-price">
                  <span className="watchlist-row__price num">${t.price.toFixed(2)}</span>
                  <ChangeBadge percent={t.day_change_percent} />
                </span>
              </Link>
            )
          })}
      {children}
    </div>
  )
}

export default function Dashboard() {
  const [quotes, setQuotes] = useState(null)
  const [marketQuotesList, setMarketQuotesList] = useState(null)
  const [news, setNews] = useState(null)
  const [trending, setTrending] = useState(null)
  const [mostActive, setMostActive] = useState(null)
  const [gainers, setGainers] = useState(null)
  const [losers, setLosers] = useState(null)
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
    getJSON('/news')
      .then((data) => !cancelled && setNews(data))
      .catch(() => !cancelled && setNews([]))
    getJSON('/trending')
      .then((data) => !cancelled && setTrending(data))
      .catch(() => !cancelled && setTrending([]))
    getJSON('/most-active')
      .then((data) => !cancelled && setMostActive(data))
      .catch(() => !cancelled && setMostActive([]))
    getJSON('/gainers')
      .then((data) => !cancelled && setGainers(data))
      .catch(() => !cancelled && setGainers([]))
    getJSON('/losers')
      .then((data) => !cancelled && setLosers(data))
      .catch(() => !cancelled && setLosers([]))
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

      <div className="dashboard__columns">
        <section className="dashboard__section dashboard__section--news">
          <div className="dashboard__section-head">
            <h2>Latest News</h2>
          </div>
          <NewsFeed articles={news} />
        </section>

        <div className="dashboard__side">
          <section className="dashboard__section">
            <div className="dashboard__section-head">
              <h2>Watchlist &amp; Movers</h2>
            </div>
            <div className="card watchlist-table ticker-groups">
              <TickerGroup label="Watchlist" tickers={quotes} emptyMessage="No watchlist tickers yet.">
                <div className="watchlist-row watchlist-row--add" title="Coming soon">
                  <span>+ Add ticker</span>
                </div>
              </TickerGroup>
              <TickerGroup label="Trending" tickers={trending} emptyMessage="No trending data right now." />
              <TickerGroup label="Most active" tickers={mostActive} emptyMessage="No active-trading data right now." />
              <TickerGroup label="Top gainers" tickers={gainers} emptyMessage="No gainers data right now." />
              <TickerGroup label="Top losers" tickers={losers} emptyMessage="No losers data right now." />
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
      </div>
    </div>
  )
}
