import { useState } from 'react'
import { derivePositionRow } from './positionRow'
import PortfolioTreemap from './PortfolioTreemap'
import PositionsTable from './PositionsTable'
import Skeleton from './Skeleton'
import './PortfolioOverview.css'

function formatSigned(value, digits = 2) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

/** The page's hero: one composite total-value line (serif figure + an
 * inline day-change badge, the way a real brokerage statement reads it)
 * rather than a row of equal-weight stat tiles. `portfolio` is null while
 * loading - the per-symbol day-change lookups behind it can take a while
 * for a large portfolio, so this shows a skeleton hero + table rather
 * than nothing until it resolves. */
export default function PortfolioOverview({ portfolio }) {
  const [view, setView] = useState('table')

  if (!portfolio) {
    return (
      <div className="portfolio-overview">
        <div className="portfolio-overview__hero">
          <Skeleton width="220px" height="3rem" />
        </div>
        <p className="portfolio-overview__cash">
          <Skeleton width="140px" height="0.8em" />
        </p>
        <PositionsTable positions={null} isLoading />
      </div>
    )
  }

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

      <div className="portfolio-overview__view-header">
        <span className="eyebrow">
          {view === 'table' ? 'Holdings' : "Holdings by size, colored by today's change"}
        </span>
        <div className="portfolio-overview__view-toggle" role="group" aria-label="Holdings view">
          <button
            className={`portfolio-overview__view-btn${view === 'table' ? ' portfolio-overview__view-btn--active' : ''}`}
            onClick={() => setView('table')}
          >
            Table
          </button>
          <button
            className={`portfolio-overview__view-btn${view === 'heatmap' ? ' portfolio-overview__view-btn--active' : ''}`}
            onClick={() => setView('heatmap')}
          >
            Heatmap
          </button>
        </div>
      </div>

      {view === 'heatmap' ? (
        <PortfolioTreemap positions={portfolio.positions} />
      ) : (
        <PositionsTable positions={portfolio.positions} />
      )}
    </div>
  )
}
