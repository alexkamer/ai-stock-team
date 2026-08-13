import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { deleteJSON, getJSON, postJSON } from '../api/client'
import AccountTabs from '../components/AccountTabs'
import PortfolioOverview from '../components/PortfolioOverview'
import './Brokerage.css'

export default function Brokerage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [connections, setConnections] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [error, setError] = useState(null)
  const [isConnecting, setIsConnecting] = useState(false)

  const loadPortfolio = useCallback(() => {
    getJSON('/brokerage/portfolio')
      .then(setPortfolio)
      .catch((err) => setError(err.message))
  }, [])

  const loadConnections = useCallback(() => {
    getJSON('/brokerage/connections')
      .then(setConnections)
      .then(loadPortfolio)
      .catch((err) => setError(err.message))
  }, [loadPortfolio])

  useEffect(() => {
    if (searchParams.get('connected')) {
      postJSON('/brokerage/sync')
        .then(setConnections)
        .then(loadPortfolio)
        .catch((err) => setError(err.message))
        .finally(() => setSearchParams({}, { replace: true }))
    } else {
      loadConnections()
    }
  }, [searchParams, setSearchParams, loadConnections, loadPortfolio])

  async function handleConnect() {
    setError(null)
    setIsConnecting(true)
    try {
      const redirect = `${window.location.origin}/brokerage?connected=1`
      const { redirect_uri } = await postJSON('/brokerage/connect', { custom_redirect: redirect })
      window.location.href = redirect_uri
    } catch (err) {
      setError(err.message)
      setIsConnecting(false)
    }
  }

  async function handleDisconnect(connectionId) {
    setError(null)
    try {
      await deleteJSON(`/brokerage/connections/${connectionId}`)
      loadConnections()
    } catch (err) {
      setError(err.message)
    }
  }

  const hasConnections = connections && connections.length > 0

  return (
    <div className="brokerage-page">
      <h1>Brokerage accounts</h1>
      <p className="brokerage-page__subtitle">
        Read-only. Positions and balances are fetched live and never stored here.
      </p>
      <button type="button" onClick={handleConnect} disabled={isConnecting}>
        {isConnecting ? 'Redirecting…' : 'Connect brokerage'}
      </button>
      {error && <p className="brokerage-page__error">{error}</p>}

      {hasConnections && <PortfolioOverview portfolio={portfolio} />}

      {connections?.length === 0 && <p className="brokerage-page__empty">No brokerages connected yet.</p>}

      {hasConnections && (
        <div className="brokerage-connections">
          {connections.map((connection) => (
            <div key={connection.id} className="brokerage-connections__row">
              <span className="brokerage-connections__name">{connection.brokerage_name ?? 'Unknown brokerage'}</span>
              <span className={`brokerage-connections__status brokerage-connections__status--${connection.status}`}>
                {connection.status}
              </span>
              <button type="button" onClick={() => handleDisconnect(connection.id)}>
                Disconnect
              </button>
            </div>
          ))}
        </div>
      )}

      {hasConnections && <AccountTabs connections={connections} />}
    </div>
  )
}
