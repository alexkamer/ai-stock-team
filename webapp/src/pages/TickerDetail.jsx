import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getJSON, streamSSE } from '../api/client'
import { useToolCalls } from '../components/useToolCalls'
import ToolCallPill from '../components/ToolCallPill'
import PriceChart from '../components/PriceChart'
import './TickerDetail.css'

const SENTIMENT_LABEL = { bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral' }

function SentimentBadge({ sentiment }) {
  if (!sentiment) return null
  return <span className={`sentiment-badge sentiment-badge--${sentiment}`}>{SENTIMENT_LABEL[sentiment]}</span>
}

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

function formatCompact(n) {
  if (n == null) return '—'
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return `${n}`
}

function RangeBar({ low, high, value }) {
  if (low == null || high == null || value == null || high <= low) return null
  const pct = Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100))
  return (
    <div className="range-bar">
      <div className="range-bar__track">
        <div className="range-bar__marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="range-bar__labels">
        <span className="num">${low.toFixed(2)}</span>
        <span className="num">${high.toFixed(2)}</span>
      </div>
    </div>
  )
}

export default function TickerDetail() {
  const { ticker } = useParams()
  const [quote, setQuote] = useState(null)
  const [sentiment, setSentiment] = useState(null)
  const [summary, setSummary] = useState('')
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('1mo')
  const [prices, setPrices] = useState(null)
  const [labels, setLabels] = useState(null)
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

  useEffect(() => {
    setPrices(null)
    setLabels(null)
    getJSON(`/tickers/${ticker}/history?period=${period}`)
      .then((data) => {
        setPrices(data.prices)
        setLabels(data.labels)
      })
      .catch(() => {})
  }, [ticker, period])

  if (error) return <div className="error-banner">{error}</div>

  const positive = (quote?.day_change_percent ?? 0) >= 0

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
              <span className="ticker-detail__price num">${quote.price.toFixed(2)}</span>
              <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
                {positive ? '↑' : '↓'} {Math.abs(quote.day_change_percent).toFixed(2)}% (${Math.abs(quote.day_change_abs).toFixed(2)})
              </span>
            </div>
          ) : (
            <span className="spinner" />
          )}
        </div>
      </div>

      <div className="ticker-detail__stats">
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Market cap</span>
          <span className="ticker-detail__stat-value num">
            {quote ? `$${formatCompact(quote.market_cap)}` : '—'}
          </span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">P/E ratio</span>
          <span className="ticker-detail__stat-value num">
            {quote ? quote.pe_ratio.toFixed(1) : '—'}
            {quote?.forward_pe && <span className="ticker-detail__stat-sub"> / fwd {quote.forward_pe.toFixed(1)}</span>}
          </span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Volume</span>
          <span className="ticker-detail__stat-value num">
            {quote ? formatCompact(quote.volume) : '—'}
            {quote?.avg_volume_3m && (
              <span className="ticker-detail__stat-sub"> / avg {formatCompact(quote.avg_volume_3m)}</span>
            )}
          </span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Dividend yield</span>
          <span className="ticker-detail__stat-value num">
            {quote?.dividend_yield ? `${quote.dividend_yield.toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="card ticker-detail__stat ticker-detail__stat--wide">
          <span className="ticker-detail__stat-label">52-week range</span>
          {quote ? (
            <RangeBar low={quote.fifty_two_week_low} high={quote.fifty_two_week_high} value={quote.price} />
          ) : (
            <span className="ticker-detail__stat-value num">—</span>
          )}
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">52-week change</span>
          <span
            className={`ticker-detail__stat-value num ${
              quote?.fifty_two_week_change_percent != null
                ? quote.fifty_two_week_change_percent >= 0
                  ? 'ticker-detail__stat-value--good'
                  : 'ticker-detail__stat-value--bad'
                : ''
            }`}
          >
            {quote?.fifty_two_week_change_percent != null
              ? `${quote.fifty_two_week_change_percent >= 0 ? '+' : ''}${quote.fifty_two_week_change_percent.toFixed(1)}%`
              : '—'}
          </span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Beta</span>
          <span className="ticker-detail__stat-value num">{quote?.beta != null ? quote.beta.toFixed(2) : '—'}</span>
        </div>
        <div className="card ticker-detail__stat ticker-detail__stat--wide">
          <span className="ticker-detail__stat-label">Analyst rating</span>
          <span className="ticker-detail__stat-value">
            {quote?.analyst_rating ?? '—'}
            {quote?.analyst_target_price && (
              <span className="ticker-detail__stat-sub num"> / target ${quote.analyst_target_price.toFixed(0)}</span>
            )}
          </span>
        </div>
      </div>

      <div className={`card ticker-detail__summary ticker-detail__summary--${sentiment?.sentiment ?? 'pending'}`}>
        <div className="ticker-detail__summary-head">
          <span className="eyebrow">AI sentiment read</span>
          <SentimentBadge sentiment={sentiment?.sentiment} />
        </div>
        {calls.length > 0 && (
          <div className="ticker-detail__pills">
            {calls.map((c, i) => (
              <ToolCallPill key={i} toolName={c.toolName} done={c.done} />
            ))}
          </div>
        )}
        <p>{sentiment?.summary ?? (summary || (quote ? 'Reading recent headlines…' : ''))}</p>
      </div>

      <div className="card">
        <PriceChart prices={prices} labels={labels} period={period} onPeriodChange={setPeriod} positive={positive} />
      </div>

      {quote?.news_headlines && (
        <div className="card ticker-detail__news">
          <span className="eyebrow">Recent news</span>
          <ul>
            {quote.news_headlines.map((headline, i) => (
              <li key={i} className="ticker-detail__news-row">
                {headline}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
