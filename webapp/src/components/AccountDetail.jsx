import { useEffect, useState } from 'react'
import { getJSON } from '../api/client'
import PositionsTable from './PositionsTable'
import Skeleton from './Skeleton'
import SkeletonRows from './SkeletonRows'
import './AccountDetail.css'

const TRANSACTION_SKELETON_WIDTHS = ['70px', '50px', '80%', '55px']

/** Positions/balances/transactions for one account - always rendered as
 * tables, no expand/collapse. Refetches whenever accountId changes.
 * Keeps every section's real structure (labels, table headers) on screen
 * immediately, with skeleton placeholders standing in for the numbers
 * until they arrive. */
export default function AccountDetail({ accountId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    setData(null)
    setError(null)
    setIsLoading(true)
    Promise.all([
      getJSON(`/brokerage/accounts/${accountId}/positions`),
      getJSON(`/brokerage/accounts/${accountId}/balances`),
      getJSON(`/brokerage/accounts/${accountId}/transactions`),
    ])
      .then(([positions, balances, transactions]) => setData({ positions, balances, transactions }))
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false))
  }, [accountId])

  if (error) return <p className="account-detail__error">{error}</p>

  return (
    <div className="account-detail">
      <div className="account-detail__balances">
        {isLoading ? (
          <Skeleton width="260px" height="0.9em" />
        ) : (
          data.balances.map((balance) => (
            <span key={balance.currency} className="num">
              {balance.currency} {balance.cash.toFixed(2)} cash · {balance.buying_power.toFixed(2)} buying power
            </span>
          ))
        )}
      </div>

      <h3>Positions</h3>
      <PositionsTable positions={data?.positions} isLoading={isLoading} />

      <h3>Recent transactions</h3>
      {!isLoading && data.transactions.length === 0 ? (
        <p className="account-detail__empty">No transactions.</p>
      ) : (
        <table className="account-detail__table account-detail__table--transactions">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Description</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <SkeletonRows columns={4} widths={TRANSACTION_SKELETON_WIDTHS} />
            ) : (
              data.transactions.map((activity) => (
                <tr key={activity.id}>
                  <td className="num">{activity.trade_date?.slice(0, 10)}</td>
                  <td>
                    {activity.type && (
                      <span
                        className={`account-detail__transaction-type account-detail__transaction-type--${activity.type.toLowerCase()}`}
                      >
                        {activity.type}
                      </span>
                    )}
                  </td>
                  <td>{activity.description}</td>
                  <td className={`num ${activity.amount == null ? '' : activity.amount >= 0 ? 'text-good' : 'text-critical'}`}>
                    {activity.amount == null ? '—' : `${activity.amount >= 0 ? '+' : ''}${activity.amount.toFixed(2)}`}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
