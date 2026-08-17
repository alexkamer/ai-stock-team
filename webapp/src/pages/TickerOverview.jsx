import { Link, useOutletContext } from 'react-router-dom'
import ToolCallPill from '../components/ToolCallPill'
import Sparkline from '../components/Sparkline'

const SENTIMENT_LABEL = { bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral' }

function SimilarTickers({ tickers }) {
  return (
    <div className="card ticker-detail__similar">
      <span className="eyebrow">Similar tickers</span>
      {tickers === null
        ? Array.from({ length: 5 }, (_, i) => <div key={i} className="similar-row similar-row--loading" />)
        : tickers.length === 0
        ? <div className="similar-row similar-row--empty">No comparable tickers found.</div>
        : tickers.map((t) => {
            const positive = t.day_change_percent >= 0
            return (
              <Link key={t.ticker} to={`/tickers/${t.ticker}`} className="similar-row">
                <span className="similar-row__name">
                  <span className="similar-row__ticker">{t.ticker}</span>
                  <span className="similar-row__company">{t.company_name}</span>
                </span>
                <Sparkline values={t.day_prices} width={56} height={24} positive={positive} />
                <span className="similar-row__price-block">
                  <span className="similar-row__price num">{t.price.toFixed(2)}</span>
                  <span className={`change-badge ${positive ? 'change-badge--good' : 'change-badge--bad'}`}>
                    {positive ? '+' : ''}{t.day_change_percent.toFixed(2)}%
                  </span>
                </span>
              </Link>
            )
          })}
    </div>
  )
}

function SentimentBadge({ sentiment }) {
  if (!sentiment) return null
  return <span className={`sentiment-badge sentiment-badge--${sentiment}`}>{SENTIMENT_LABEL[sentiment]}</span>
}

function formatCompact(n) {
  if (n == null) return '—'
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return `${n}`
}

function RangeBar({ low, high, value, valueLabel = 'Current price', secondaryValue, secondaryLabel }) {
  if (low == null || high == null || value == null || high <= low) return null
  const toPct = (v) => Math.max(0, Math.min(100, ((v - low) / (high - low)) * 100))
  return (
    <div className="range-bar">
      <div className="range-bar__track">
        <div className="range-bar__marker" style={{ left: `${toPct(value)}%` }} title={valueLabel} />
        {secondaryValue != null && (
          <div
            className="range-bar__marker range-bar__marker--secondary"
            style={{ left: `${toPct(secondaryValue)}%` }}
            title={secondaryLabel}
          />
        )}
      </div>
      {secondaryValue != null && (
        <div className="range-bar__legend">
          <span className="range-bar__legend-item">
            <span className="range-bar__legend-swatch range-bar__legend-swatch--primary" /> {valueLabel}
          </span>
          <span className="range-bar__legend-item">
            <span className="range-bar__legend-swatch range-bar__legend-swatch--secondary" /> {secondaryLabel}
          </span>
        </div>
      )}
      <div className="range-bar__labels">
        <span className="num">{low.toFixed(2)}</span>
        <span className="num">{high.toFixed(2)}</span>
      </div>
    </div>
  )
}

export default function TickerOverview() {
  const { quote, sentiment, summary, calls } = useOutletContext()

  return (
    <div className="ticker-detail__columns">
      <div className="ticker-detail__main">
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
          <div className="card ticker-detail__stat">
            <span
              className="ticker-detail__stat-label"
              title="Average of analysts' 1 (Strong Buy) to 5 (Strong Sell) ratings"
            >
              Analyst rating
            </span>
            <span className="ticker-detail__stat-value">{quote?.analyst_rating ?? '—'}</span>
            <span className="ticker-detail__stat-caption">1 = Strong Buy · 5 = Strong Sell</span>
          </div>
          <div className="card ticker-detail__stat ticker-detail__stat--wide">
            <span className="ticker-detail__stat-label">
              Analyst price target
              {quote?.analyst_count ? ` (${quote.analyst_count} analysts)` : ''}
            </span>
            {quote?.analyst_target_low != null && quote?.analyst_target_high != null ? (
              <RangeBar
                low={quote.analyst_target_low}
                high={quote.analyst_target_high}
                value={quote.price}
                secondaryValue={quote.analyst_target_price}
                secondaryLabel={`Mean target ${quote.analyst_target_price?.toFixed(0)}`}
              />
            ) : (
              <span className="ticker-detail__stat-value num">—</span>
            )}
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
      </div>

      <div className="ticker-detail__side">
        <SimilarTickers tickers={quote?.similar_tickers ?? (quote === null ? null : [])} />
      </div>
    </div>
  )
}
