import { useEffect, useState } from 'react'
import { getJSON } from '../api/client'
import PositionsTable from './PositionsTable'
import './AccountDetail.css'

/** Positions/balances/transactions for one account - always rendered as
 * tables, no expand/collapse. Refetches whenever accountId changes. */
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

  if (isLoading) return <p className="account-detail__empty">Loading…</p>
  if (error) return <p className="account-detail__error">{error}</p>
  if (!data) return null

  return (
    <div className="account-detail">
      {data.balances.length > 0 && (
        <div className="account-detail__balances">
          {data.balances.map((balance) => (
            <span key={balance.currency} className="num">
              {balance.currency} {balance.cash.toFixed(2)} cash · {balance.buying_power.toFixed(2)} buying power
            </span>
          ))}
        </div>
      )}

      <h3>Positions</h3>
      <PositionsTable positions={data.positions} />

      <h3>Recent transactions</h3>
      {data.transactions.length === 0 ? (
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
            {data.transactions.map((activity) => (
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
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
