import './ComparisonTable.css'

function formatCompact(n) {
  if (n == null) return null
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

function signedPct(n) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

const ROWS = [
  { key: 'price', label: 'Price', get: (t) => (t.price != null ? `$${t.price.toFixed(2)}` : null) },
  {
    key: 'dayChange',
    label: 'Day change',
    get: (t) => (t.dayChangePercent != null ? signedPct(t.dayChangePercent) : null),
    good: (t) => t.dayChangePercent >= 0,
  },
  { key: 'marketCap', label: 'Market cap', get: (t) => (t.marketCap != null ? `$${formatCompact(t.marketCap)}` : null) },
  { key: 'peRatio', label: 'P/E ratio', get: (t) => (t.peRatio != null ? t.peRatio.toFixed(1) : null) },
  {
    key: 'history',
    label: 'Period change',
    get: (t) => (t.history != null ? `${t.history.period} ${signedPct(t.history.percent_change)}` : null),
    good: (t) => t.history?.percent_change >= 0,
  },
]

/** Side-by-side stat comparison for 2+ tickers the user has selected from the canvas. */
export default function ComparisonTable({ tickers, onClear }) {
  return (
    <div className="comparison-table">
      <div className="comparison-table__header">
        <span className="eyebrow">Comparing {tickers.map((t) => t.ticker).join(' vs ')}</span>
        <button type="button" className="comparison-table__clear" onClick={onClear}>
          Clear
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th />
            {tickers.map((t) => (
              <th key={t.ticker}>{t.ticker}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.filter((row) => tickers.some((t) => row.get(t) != null)).map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.label}</th>
              {tickers.map((t) => {
                const value = row.get(t)
                const good = row.good?.(t)
                return (
                  <td
                    key={t.ticker}
                    className={`num${good == null ? '' : good ? ' comparison-table__good' : ' comparison-table__bad'}`}
                  >
                    {value ?? '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
