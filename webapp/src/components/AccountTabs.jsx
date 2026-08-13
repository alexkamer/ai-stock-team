import { useEffect, useState } from 'react'
import AccountDetail from './AccountDetail'
import './AccountTabs.css'

/** Flattens accounts across every connection into one tab strip, so
 * switching brokerages/accounts doesn't require expanding anything. */
export default function AccountTabs({ connections }) {
  const accounts = connections.flatMap((connection) =>
    connection.accounts.map((account) => ({ ...account, brokerageName: connection.brokerage_name }))
  )
  const [activeAccountId, setActiveAccountId] = useState(accounts[0]?.id ?? null)

  useEffect(() => {
    if (!accounts.some((account) => account.id === activeAccountId)) {
      setActiveAccountId(accounts[0]?.id ?? null)
    }
  }, [accounts, activeAccountId])

  if (accounts.length === 0) return null

  return (
    <div className="account-tabs">
      <div className="account-tabs__strip">
        {accounts.map((account) => (
          <button
            key={account.id}
            type="button"
            className={`account-tabs__tab ${account.id === activeAccountId ? 'account-tabs__tab--active' : ''}`}
            onClick={() => setActiveAccountId(account.id)}
          >
            <span className="account-tabs__tab-brokerage">{account.brokerageName}</span>
            <span className="account-tabs__tab-name">{account.name ?? 'Account'}</span>
          </button>
        ))}
      </div>
      {activeAccountId != null && <AccountDetail accountId={activeAccountId} />}
    </div>
  )
}
