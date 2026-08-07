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

export default function TickerDetail() {
  const { ticker } = useParams()
  const [quote, setQuote] = useState(null)
  const [sentiment, setSentiment] = useState(null)
  const [summary, setSummary] = useState('')
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('1mo')
  const [prices, setPrices] = useState(null)
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
    getJSON(`/tickers/${ticker}/history?period=${period}`)
      .then((data) => setPrices(data.prices))
      .catch(() => {})
  }, [ticker, period])

  if (error) return <div className="error-banner">{error}</div>

  const positive = (quote?.day_change_percent ?? 0) >= 0

  return (
    <div className="ticker-detail">
      <div className="ticker-detail__header">
        <div>
          <span className="eyebrow">{ticker}</span>
          <h1>{quote?.company_name ?? '···'}</h1>
        </div>
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

      <div className="ticker-detail__stats">
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Market cap</span>
          <span className="ticker-detail__stat-value num">
            {quote ? `$${(quote.market_cap / 1e9).toFixed(1)}B` : '—'}
          </span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">P/E ratio</span>
          <span className="ticker-detail__stat-value num">{quote ? quote.pe_ratio.toFixed(1) : '—'}</span>
        </div>
        <div className="card ticker-detail__stat">
          <span className="ticker-detail__stat-label">Day change</span>
          <span className={`ticker-detail__stat-value num ${quote ? (positive ? 'ticker-detail__stat-value--good' : 'ticker-detail__stat-value--bad') : ''}`}>
            {quote ? `${positive ? '+' : ''}${quote.day_change_percent.toFixed(2)}%` : '—'}
          </span>
        </div>
      </div>

      <div className="card ticker-detail__summary">
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
        <PriceChart prices={prices} period={period} onPeriodChange={setPeriod} positive={positive} />
      </div>

      {quote?.news_headlines && (
        <div className="card ticker-detail__news">
          <span className="eyebrow">Recent news</span>
          <ul>
            {quote.news_headlines.map((headline, i) => (
              <li key={i}>{headline}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
