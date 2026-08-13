import { derivePositionRow } from './positionRow'
import PositionsTable from './PositionsTable'
import './PortfolioOverview.css'

function formatSigned(value, digits = 2) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

/** The page's hero: one composite total-value line (serif figure + an
 * inline day-change badge, the way a real brokerage statement reads it)
 * rather than a row of equal-weight stat tiles. `portfolio` is null while
 * loading - render nothing rather than a placeholder to avoid layout jump. */
export default function PortfolioOverview({ portfolio }) {
  if (!portfolio) return null

  const rows = portfolio.positions.map(derivePositionRow)
  const knownDayChangeRows = rows.filter((row) => row.dayChangeDollar != null)
  const dayChangeDollar = knownDayChangeRows.length
    ? knownDayChangeRows.reduce((sum, row) => sum + row.dayChangeDollar, 0)
    : null
  const previousTotalValue = dayChangeDollar != null ? portfolio.total_value - dayChangeDollar : null
  const dayChangePercent =
    dayChangeDollar != null && previousTotalValue ? (dayChangeDollar / previousTotalValue) * 100 : null
  const totalCash = portfolio.balances.reduce((sum, balance) => sum + balance.cash, 0)
  const dayChangeSign = dayChangeDollar == null ? '' : dayChangeDollar >= 0 ? 'good' : 'bad'

  return (
    <div className="portfolio-overview">
      <div className="portfolio-overview__hero">
        <span className="portfolio-overview__value">{portfolio.total_value.toFixed(2)}</span>
        {dayChangeDollar != null && (
          <span className={`portfolio-overview__change portfolio-overview__change--${dayChangeSign}`}>
            {formatSigned(dayChangeDollar)} ({formatSigned(dayChangePercent)}%) today
          </span>
        )}
      </div>
      {totalCash > 0 && <p className="portfolio-overview__cash">{totalCash.toFixed(2)} cash uninvested</p>}

      <PositionsTable positions={portfolio.positions} />
    </div>
  )
}
