import './TickerBadge.css'

/** Small "TICKER +1.23%" pill shown on a news article that's attributed to
 * a specific stock (see ticker/ticker_day_change_percent on article objects
 * from GET /news) - omitted entirely if the day change wasn't available. */
export default function TickerBadge({ ticker, percent }) {
  if (!ticker || percent === null || percent === undefined) return null
  const positive = percent >= 0
  return (
    <span className={`ticker-badge ${positive ? 'ticker-badge--good' : 'ticker-badge--bad'}`}>
      {ticker} {positive ? '+' : ''}{percent.toFixed(2)}%
    </span>
  )
}
