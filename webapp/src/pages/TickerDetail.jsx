import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { streamSSE } from '../api/client'
import { useToolCalls } from '../components/useToolCalls'
import './TickerDetail.css'

function CompanyLogo({ domain, ticker }) {
  const [failed, setFailed] = useState(false)
  if (!domain || failed) {
    return <div className="company-logo company-logo--fallback">{ticker.slice(0, 2)}</div>
  }
  return (
    <img
      className="company-logo"
      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`}
      alt=""
      onError={() => setFailed(true)}
    />
  )
}

function formatUpdatedAt(date) {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

const TABS = [
  { to: '', label: 'Overview', end: true },
  { to: 'charts', label: 'Charts' },
  { to: 'news', label: 'News' },
  { to: 'team', label: 'Team Analysis' },
]

export default function TickerDetail() {
  const { ticker } = useParams()
  const [quote, setQuote] = useState(null)
  const [sentiment, setSentiment] = useState(null)
  const [summary, setSummary] = useState('')
  const [error, setError] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  const { calls, handleEvent, reset } = useToolCalls()
  const controllerRef = useRef(null)

  useEffect(() => {
    setQuote(null)
    setSentiment(null)
    setSummary('')
    setError(null)
    reset()
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    streamSSE(`/tickers/${ticker}`, {
      signal: controller.signal,
      onEvent: (eventName, data) => {
        if (eventName === 'text') {
          setSummary((prev) => prev + data.delta)
        } else if (eventName === 'quote') {
          setQuote(data)
          setUpdatedAt(new Date())
        } else if (eventName === 'sentiment') {
          setSentiment(data)
        } else if (eventName === 'error') {
          setError(data.detail)
        } else {
          handleEvent(eventName, data)
        }
      },
    }).catch((e) => {
      if (e.name !== 'AbortError') setError(e.message)
    })

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  if (error) return <div className="error-banner">{error}</div>

  const positive = (quote?.day_change_percent ?? 0) >= 0
  const previousClose = quote ? quote.price - quote.day_change_abs : null

  return (
    <div className="ticker-detail">
      <div className={`ticker-detail__hero${quote ? (positive ? ' ticker-detail__hero--good' : ' ticker-detail__hero--bad') : ''}`}>
        {updatedAt && <span className="ticker-detail__updated-at">Updated {formatUpdatedAt(updatedAt)}</span>}
        <div className="ticker-detail__hero-main">
          <CompanyLogo domain={quote?.logo_domain} ticker={ticker} />
          <div className="ticker-detail__identity">
            <div className="ticker-detail__identity-line">
              <span className="eyebrow">{ticker}</span>
              {quote?.sector && <span className="sector-tag">{quote.sector}</span>}
            </div>
            <h1>{quote?.company_name ?? '···'}</h1>
          </div>
        </div>
        <div className="ticker-detail__hero-side">
          {quote ? (
            <div className="ticker-detail__price-block">
              <span className="ticker-detail__price num">{quote.price.toFixed(2)}</span>
              <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
                {positive ? '↑' : '↓'} {Math.abs(quote.day_change_abs).toFixed(2)} ({Math.abs(quote.day_change_percent).toFixed(2)}%)
              </span>
              {quote.extended_hours && (
                <div className="ticker-detail__extended-price">
                  <span className="ticker-detail__extended-label">
                    {quote.extended_hours.session === 'pre' ? 'Pre-market' : 'After hours'}
                  </span>
                  <span className="ticker-detail__extended-value num">{quote.extended_hours.price.toFixed(2)}</span>
                  <span
                    className={`change-badge change-badge--small ${
                      quote.extended_hours.percent >= 0 ? 'change-badge--good' : 'change-badge--bad'
                    }`}
                  >
                    {quote.extended_hours.percent >= 0 ? '↑' : '↓'} {Math.abs(quote.extended_hours.absolute).toFixed(2)}{' '}
                    ({Math.abs(quote.extended_hours.percent).toFixed(2)}%)
                  </span>
                </div>
              )}
            </div>
          ) : (
            <span className="spinner" />
          )}
        </div>
      </div>

      <div className="ticker-detail__tabs">
        {TABS.map((tab) => (
          <NavLink
            key={tab.label}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `ticker-detail__tab${isActive ? ' ticker-detail__tab--active' : ''}`}
          >
            {tab.label}
          </NavLink>
        ))}
      </div>

      <Outlet context={{ ticker, quote, sentiment, summary, calls, positive, previousClose }} />
    </div>
  )
}
