import { useEffect, useMemo, useState } from 'react'
import { getJSON, postJSON } from '../api/client'
import NewsFeed from './NewsFeed'
import PortfolioDigest from './PortfolioDigest'
import { derivePositionRow } from './positionRow'
import PortfolioTreemap from './PortfolioTreemap'
import PositionsTable from './PositionsTable'
import Skeleton from './Skeleton'
import SkeletonRows from './SkeletonRows'
import './PortfolioOverview.css'

// Keeps the /news query string bounded for portfolios with many distinct
// holdings - the backend fans this out to one yfinance call per symbol.
const MAX_NEWS_SYMBOLS = 40

const ORDER_SKELETON_WIDTHS = ['70px', '50px', '80%', '55px']

// Matches Brokerage.jsx's own portfolio refresh cadence, which covers "All
// accounts" - this just keeps a single selected account's positions from
// going stale too, since those come from a separate, cached-until-now fetch.
const PRICE_REFRESH_INTERVAL_MS = 30_000

function formatSigned(value, digits = 2) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

function formatUpdatedAt(date) {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

/** The page's hero: one composite total-value line (serif figure + an
 * inline day-change badge, the way a real brokerage statement reads it)
 * rather than a row of equal-weight stat tiles. `portfolio` is null while
 * loading - the per-symbol day-change lookups behind it can take a while
 * for a large portfolio, so this shows a skeleton hero + table rather
 * than nothing until it resolves.
 *
 * Positions/Orders and the account picker are independent of each other:
 * switching accounts re-scopes whichever tab is active, rather than
 * resetting to Positions. "All accounts" reuses the already-loaded
 * combined `portfolio` for positions; everything else (combined orders,
 * every account's positions/orders) is prefetched in the background as
 * soon as the account list is known, so switching tabs/accounts reads
 * from cache instead of round-tripping. */
export default function PortfolioOverview({ portfolio, connections, updatedAt }) {
  const accounts = useMemo(
    () =>
      (connections ?? []).flatMap((connection) =>
        connection.accounts.map((account) => ({ ...account, brokerageName: connection.brokerage_name }))
      ),
    [connections]
  )

  const [tab, setTab] = useState('positions')
  const [view, setView] = useState('table')
  const [afterHours, setAfterHours] = useState(false)
  const [accountId, setAccountId] = useState('all')
  const [positionsByAccount, setPositionsByAccount] = useState({})
  const [ordersByAccount, setOrdersByAccount] = useState({})
  const [newsByAccount, setNewsByAccount] = useState({})
  // Digest is portfolio-wide (not per-account) and, unlike every other bit
  // of state on this page, is never fetched automatically - it's a real
  // Bedrock call, only ever triggered by PortfolioDigest's button.
  const [digest, setDigest] = useState(null)

  useEffect(() => {
    if (accounts.length === 0) return

    // Deferred to idle time so this background warm-up doesn't compete
    // with the page's own critical requests (connections/portfolio) for
    // the browser's limited per-host connection slots - those should
    // finish and paint first, then the cache fills in quietly.
    const requestIdle = window.requestIdleCallback ?? ((callback) => setTimeout(callback, 300))
    const cancelIdle = window.cancelIdleCallback ?? clearTimeout

    const handle = requestIdle(() => {
      getJSON('/brokerage/orders').then((orders) =>
        setOrdersByAccount((prev) => (prev.all ? prev : { ...prev, all: orders }))
      )
      accounts.forEach((account) => {
        getJSON(`/brokerage/accounts/${account.id}/positions`).then((positions) =>
          setPositionsByAccount((prev) => (prev[account.id] ? prev : { ...prev, [account.id]: positions }))
        )
        getJSON(`/brokerage/accounts/${account.id}/transactions`).then((orders) =>
          setOrdersByAccount((prev) => (prev[account.id] ? prev : { ...prev, [account.id]: orders }))
        )
      })
    })
    return () => cancelIdle(handle)
  }, [accounts])

  useEffect(() => {
    if (accountId === 'all') return
    const interval = setInterval(() => {
      if (document.hidden) return
      getJSON(`/brokerage/accounts/${accountId}/positions`).then((positions) =>
        setPositionsByAccount((prev) => ({ ...prev, [accountId]: positions }))
      )
    }, PRICE_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [accountId])

  const positionsForNews = accountId === 'all' ? portfolio?.positions : positionsByAccount[accountId]

  useEffect(() => {
    if (tab !== 'news' || newsByAccount[accountId] !== undefined || !positionsForNews) return
    const symbols = [...new Set(positionsForNews.map((p) => p.symbol).filter(Boolean))].slice(0, MAX_NEWS_SYMBOLS)
    if (symbols.length === 0) {
      setNewsByAccount((prev) => ({ ...prev, [accountId]: [] }))
      return
    }
    getJSON(`/news?symbols=${symbols.join(',')}`)
      .then((data) => setNewsByAccount((prev) => ({ ...prev, [accountId]: data })))
      .catch(() => setNewsByAccount((prev) => ({ ...prev, [accountId]: [] })))
  }, [tab, accountId, positionsForNews, newsByAccount])

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

  const knownExtendedHoursRows = rows.filter((row) => row.extendedHoursDollarChange != null)
  const extendedHoursDollar = knownExtendedHoursRows.length
    ? knownExtendedHoursRows.reduce((sum, row) => sum + row.extendedHoursDollarChange, 0)
    : null
  const extendedHoursPercent =
    extendedHoursDollar != null && portfolio.total_value
      ? (extendedHoursDollar / portfolio.total_value) * 100
      : null
  const extendedHoursSession = knownExtendedHoursRows[0]?.extendedHoursSession ?? null
  const extendedHoursSign = extendedHoursDollar == null ? '' : extendedHoursDollar >= 0 ? 'good' : 'bad'
  const extendedHoursTotalValue = extendedHoursDollar != null ? portfolio.total_value + extendedHoursDollar : null

  const positions = accountId === 'all' ? portfolio.positions : positionsByAccount[accountId]
  const isLoadingPositions = accountId !== 'all' && !positionsByAccount[accountId]
  const orders = ordersByAccount[accountId]
  const isLoadingOrders = tab === 'orders' && !orders

  async function generateDigest() {
    setDigest('loading')
    try {
      setDigest(await postJSON('/brokerage/digest'))
    } catch (err) {
      setDigest({ error: err.message })
    }
  }

  return (
    <div className="portfolio-overview">
      <div className="portfolio-overview__hero">
        <span className="portfolio-overview__value">{portfolio.total_value.toFixed(2)}</span>
        {dayChangeDollar != null && (
          <span className={`portfolio-overview__change portfolio-overview__change--${dayChangeSign}`}>
            {formatSigned(dayChangeDollar)} ({formatSigned(dayChangePercent)}%) today
          </span>
        )}
        {updatedAt && <span className="portfolio-overview__updated-at">Updated {formatUpdatedAt(updatedAt)}</span>}
      </div>
      {afterHours && extendedHoursTotalValue != null && (
        <div className="portfolio-overview__extended">
          <span className="portfolio-overview__extended-label">
            {extendedHoursSession === 'pre' ? 'Pre-market' : 'After hours'}
          </span>
          <span className="portfolio-overview__extended-value">{extendedHoursTotalValue.toFixed(2)}</span>
          <span className={`portfolio-overview__change portfolio-overview__change--${extendedHoursSign}`}>
            {formatSigned(extendedHoursDollar)} ({formatSigned(extendedHoursPercent)}%)
          </span>
        </div>
      )}
      {totalCash > 0 && <p className="portfolio-overview__cash">{totalCash.toFixed(2)} cash uninvested</p>}

      <div className="portfolio-overview__tabs">
        <button
          type="button"
          className={`portfolio-overview__tab ${tab === 'positions' ? 'portfolio-overview__tab--active' : ''}`}
          onClick={() => setTab('positions')}
        >
          Positions
        </button>
        <button
          type="button"
          className={`portfolio-overview__tab ${tab === 'orders' ? 'portfolio-overview__tab--active' : ''}`}
          onClick={() => setTab('orders')}
        >
          Orders
        </button>
        <button
          type="button"
          className={`portfolio-overview__tab ${tab === 'news' ? 'portfolio-overview__tab--active' : ''}`}
          onClick={() => setTab('news')}
        >
          News
        </button>
        <button
          type="button"
          className={`portfolio-overview__tab ${tab === 'digest' ? 'portfolio-overview__tab--active' : ''}`}
          onClick={() => setTab('digest')}
        >
          Daily Digest
        </button>
      </div>

      <div className="portfolio-overview__view-header">
        <span className="eyebrow">
          {tab === 'orders'
            ? 'Orders'
            : tab === 'news'
              ? 'News for your holdings'
              : tab === 'digest'
                ? 'Daily Digest'
                : view === 'table'
                  ? 'Holdings'
                  : "Holdings by size, colored by today's change"}
        </span>
        <div className="portfolio-overview__controls">
          {tab !== 'digest' && (
            <select
              className="portfolio-overview__account-select"
              value={accountId}
              onChange={(event) => setAccountId(event.target.value === 'all' ? 'all' : Number(event.target.value))}
              aria-label="Account"
            >
              <option value="all">All accounts</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.brokerageName} · {account.name ?? 'Account'}
                </option>
              ))}
            </select>
          )}
          {tab === 'positions' && view === 'table' && (
            <button
              type="button"
              className={`portfolio-overview__view-btn portfolio-overview__ah-toggle${afterHours ? ' portfolio-overview__view-btn--active' : ''}`}
              onClick={() => setAfterHours((prev) => !prev)}
              aria-pressed={afterHours}
            >
              After Hours
            </button>
          )}
          {tab === 'positions' && (
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
          )}
        </div>
      </div>

      {tab === 'positions' ? (
        view === 'heatmap' ? (
          <PortfolioTreemap positions={positions ?? []} />
        ) : (
          <PositionsTable positions={positions} isLoading={isLoadingPositions} showAfterHours={afterHours} />
        )
      ) : tab === 'news' ? (
        <NewsFeed
          articles={newsByAccount[accountId] ?? null}
          showTicker
          summarizable
          emptyMessage="No recent headlines for your holdings."
        />
      ) : tab === 'digest' ? (
        <PortfolioDigest digest={digest} onGenerate={generateDigest} />
      ) : isLoadingOrders ? (
        <table className="portfolio-overview__table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Description</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            <SkeletonRows columns={4} widths={ORDER_SKELETON_WIDTHS} />
          </tbody>
        </table>
      ) : orders.length === 0 ? (
        <p className="portfolio-overview__empty">No orders.</p>
      ) : (
        <table className="portfolio-overview__table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Description</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((activity) => (
              <tr key={activity.id}>
                <td className="num">{activity.trade_date?.slice(0, 10)}</td>
                <td>
                  {activity.type && (
                    <span
                      className={`portfolio-overview__order-type portfolio-overview__order-type--${activity.type.toLowerCase()}`}
                    >
                      {activity.type}
                    </span>
                  )}
                </td>
                <td>
                  {activity.description}
                  {accountId === 'all' && activity.account_name && (
                    <span className="portfolio-overview__order-account"> · {activity.account_name}</span>
                  )}
                </td>
                <td className={`num ${activity.amount == null ? '' : activity.amount >= 0 ? 'text-good' : 'text-critical'}`}>
                  {activity.amount == null ? '—' : `${activity.amount >= 0 ? '+' : ''}${activity.amount.toFixed(2)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
