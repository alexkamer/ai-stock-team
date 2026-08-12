import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import NewsFeed from '../components/NewsFeed'
import NewsCarousel from '../components/NewsCarousel'
import NewsColumns from '../components/NewsColumns'
import Sparkline from '../components/Sparkline'
import { useWatchlist } from '../context/WatchlistContext'
import './Dashboard.css'

// Matches NEWS_CATEGORY_TICKERS' keys on the backend.
const NEWS_CATEGORIES = [
  { key: 'top', label: 'Top Stories' },
  { key: 'markets', label: 'Markets & Economy' },
  { key: 'tech', label: 'Tech & AI' },
]

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
function TickerGroup({ label, to, tickers, emptyMessage, onRemove, children }) {
  return (
    <div className="ticker-group">
      {to ? (
        <Link to={to} className="ticker-group__label ticker-group__label--link">
          {label}
        </Link>
      ) : (
        <span className="ticker-group__label">{label}</span>
      )}
      {tickers === null
        ? Array.from({ length: 3 }, (_, i) => <div key={i} className="watchlist-row watchlist-row--loading" />)
        : tickers.length === 0
        ? <div className="watchlist-row watchlist-row--empty">{emptyMessage}</div>
        : tickers.map((t) => {
            const positive = t.day_change_percent >= 0
            return (
              <div key={t.ticker} className="watchlist-row watchlist-row--linked">
                <Link to={`/tickers/${t.ticker}`} className="watchlist-row__link">
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
                {onRemove && (
                  <button
                    type="button"
                    className="watchlist-row__remove"
                    aria-label={`Remove ${t.ticker} from watchlist`}
                    onClick={() => onRemove(t.ticker)}
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })}
      {children}
    </div>
  )
}

/** Text input + submit for adding a ticker to the watchlist - validated
 * against a real quote lookup before adding so a typo fails fast with a
 * message instead of silently sitting in the list forever. */
function AddTickerRow({ onAdd }) {
  const [value, setValue] = useState('')
  const [checking, setChecking] = useState(false)
  const [invalid, setInvalid] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const symbol = value.trim().toUpperCase()
    if (!symbol || checking) return
    setChecking(true)
    setInvalid(false)
    try {
      const quotes = await getJSON(`/watchlist?symbols=${symbol}`)
      if (quotes.length === 0) {
        setInvalid(true)
      } else {
        onAdd(symbol)
        setValue('')
      }
    } catch {
      setInvalid(true)
    } finally {
      setChecking(false)
    }
  }

  return (
    <form className="watchlist-row watchlist-row--add" onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          setInvalid(false)
        }}
        placeholder="+ Add ticker"
        disabled={checking}
        className="watchlist-row__add-input"
      />
      {invalid && <span className="watchlist-row__add-error">Not found</span>}
    </form>
  )
}

export default function Dashboard() {
  const { tickers: watchlistTickers, addTicker, removeTicker } = useWatchlist()
  const [quotes, setQuotes] = useState(null)
  const [marketQuotesList, setMarketQuotesList] = useState(null)
  const [news, setNews] = useState(null)
  const [categoryNews, setCategoryNews] = useState(() =>
    Object.fromEntries(NEWS_CATEGORIES.map((c) => [c.key, null]))
  )
  const [moreNews, setMoreNews] = useState(null)
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
    if (watchlistTickers.length === 0) {
      setQuotes([])
      setNews([])
      return
    }
    let cancelled = false
    getJSON(`/watchlist?symbols=${watchlistTickers.join(',')}`)
      .then((data) => !cancelled && setQuotes(data))
      .catch((e) => !cancelled && setError(e.message))
    getJSON(`/news?symbols=${watchlistTickers.join(',')}`)
      .then((data) => !cancelled && setNews(data))
      .catch(() => !cancelled && setNews([]))
    return () => {
      cancelled = true
    }
  }, [watchlistTickers])

  useEffect(() => {
    let cancelled = false
    getJSON(`/watchlist?symbols=${MARKET_INSTRUMENTS.map((i) => i.ticker).join(',')}`)
      .then((data) => !cancelled && setMarketQuotesList(data))
      .catch(() => {})
    getJSON('/markets/stocks/trending')
      .then((data) => !cancelled && setTrending(data.items))
      .catch(() => !cancelled && setTrending([]))
    getJSON('/markets/stocks/most-active')
      .then((data) => !cancelled && setMostActive(data.items))
      .catch(() => !cancelled && setMostActive([]))
    getJSON('/markets/stocks/gainers')
      .then((data) => !cancelled && setGainers(data.items))
      .catch(() => !cancelled && setGainers([]))
    getJSON('/markets/stocks/losers')
      .then((data) => !cancelled && setLosers(data.items))
      .catch(() => !cancelled && setLosers([]))
    NEWS_CATEGORIES.forEach(({ key }) => {
      getJSON(`/news?category=${key}&limit=6`)
        .then((data) => !cancelled && setCategoryNews((prev) => ({ ...prev, [key]: data })))
        .catch(() => !cancelled && setCategoryNews((prev) => ({ ...prev, [key]: [] })))
    })
    getJSON('/news?category=more&limit=24')
      .then((data) => !cancelled && setMoreNews(data))
      .catch(() => !cancelled && setMoreNews([]))
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

  // Split headlines into a small image-led "top stories" carousel and a
  // plain list for the rest, rather than one long undifferentiated feed.
  const featured = news?.filter((a) => a.thumbnail).slice(0, 4) ?? null
  const featuredUrls = new Set((featured ?? []).map((a) => a.url))
  const rest = news?.filter((a) => !featuredUrls.has(a.url)) ?? news

  // "More News" excludes anything already surfaced above (carousel, list,
  // or one of the three category columns) so it reads as genuinely more,
  // not a re-shuffled repeat of the same top stories.
  const shownUrls = new Set([
    ...(news ?? []).map((a) => a.url),
    ...NEWS_CATEGORIES.flatMap((c) => (categoryNews[c.key] ?? []).map((a) => a.url)),
  ])
  const more = moreNews?.filter((a) => !shownUrls.has(a.url)) ?? moreNews

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
          <NewsCarousel articles={featured} />
          <NewsFeed articles={rest} />
          <NewsColumns
            columns={NEWS_CATEGORIES.map((c) => ({ ...c, articles: categoryNews[c.key] }))}
          />

          <div className="dashboard__section-head dashboard__section-head--more">
            <h2>More News</h2>
          </div>
          <NewsFeed articles={more} />
        </section>

        <div className="dashboard__side">
          <section className="dashboard__section">
            <div className="dashboard__section-head">
              <h2>Watchlist &amp; Movers</h2>
            </div>
            <div className="card watchlist-table ticker-groups">
              <TickerGroup
                label="Watchlist"
                tickers={quotes}
                emptyMessage="No watchlist tickers yet."
                onRemove={removeTicker}
              >
                <AddTickerRow onAdd={addTicker} />
              </TickerGroup>
              <TickerGroup
                label="Trending"
                to="/markets/stocks/trending"
                tickers={trending}
                emptyMessage="No trending data right now."
              />
              <TickerGroup
                label="Most active"
                to="/markets/stocks/most-active"
                tickers={mostActive}
                emptyMessage="No active-trading data right now."
              />
              <TickerGroup
                label="Top gainers"
                to="/markets/stocks/gainers"
                tickers={gainers}
                emptyMessage="No gainers data right now."
              />
              <TickerGroup
                label="Top losers"
                to="/markets/stocks/losers"
                tickers={losers}
                emptyMessage="No losers data right now."
              />
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
