import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { brokerageCache } from '../api/brokerageCache'
import { deleteJSON, getJSON, postJSON } from '../api/client'
import PortfolioOverview from '../components/PortfolioOverview'
import Skeleton from '../components/Skeleton'
import './Brokerage.css'

// Keeps holdings roughly in step with the market without hammering yfinance
// - the backend's own quote cache (core/tools._get_info) has a matching TTL,
// so a shorter interval here wouldn't actually return fresher prices anyway.
const PRICE_REFRESH_INTERVAL_MS = 30_000

/** Same trick as TickerDetail's CompanyLogo: SnapTrade's own logo URLs are
 * hotlink-protected and fail when loaded directly from the browser, so this
 * resolves a favicon through Google's service off the brokerage's domain
 * instead. */
function BrokerageLogo({ domain, name }) {
  const [failed, setFailed] = useState(false)
  if (!domain || failed) {
    return <span className="brokerage-card__initial">{name.charAt(0)}</span>
  }
  return (
    <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`} alt="" onError={() => setFailed(true)} />
  )
}

export default function Brokerage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [connections, setConnectionsState] = useState(() => brokerageCache.connections)
  const [portfolio, setPortfolioState] = useState(() => brokerageCache.portfolio)
  const [updatedAt, setUpdatedAtState] = useState(() => brokerageCache.updatedAt)
  const [error, setError] = useState(null)
  const [isConnecting, setIsConnecting] = useState(false)

  const setConnections = useCallback((data) => {
    brokerageCache.connections = data
    setConnectionsState(data)
  }, [])

  const loadPortfolio = useCallback(() => {
    getJSON('/brokerage/portfolio')
      .then((data) => {
        const now = new Date()
        brokerageCache.portfolio = data
        brokerageCache.updatedAt = now
        setPortfolioState(data)
        setUpdatedAtState(now)
      })
      .catch((err) => setError(err.message))
  }, [])

  const loadConnections = useCallback(() => {
    getJSON('/brokerage/connections')
      .then(setConnections)
      .catch((err) => setError(err.message))
  }, [setConnections])

  useEffect(() => {
    if (searchParams.get('connected')) {
      // Unlike the normal load below, this can't run in parallel: /sync writes
      // newly-discovered accounts to the DB, and /portfolio needs that write
      // committed first or it'll compute totals against the pre-sync account set.
      postJSON('/brokerage/sync')
        .then(setConnections)
        .then(loadPortfolio)
        .catch((err) => setError(err.message))
        .finally(() => setSearchParams({}, { replace: true }))
    } else {
      loadConnections()
      loadPortfolio()
    }
  }, [searchParams, setSearchParams, loadConnections, loadPortfolio, setConnections])

  useEffect(() => {
    const interval = setInterval(() => {
      if (!document.hidden) loadPortfolio()
    }, PRICE_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [loadPortfolio])

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
      <div className="brokerage-page__header">
        <div>
          <h1>Brokerage accounts</h1>
          <p className="brokerage-page__subtitle">
            Read-only. Positions and balances are fetched live and never stored here.
          </p>
        </div>
        <button type="button" onClick={handleConnect} disabled={isConnecting}>
          {isConnecting ? 'Redirecting…' : 'Connect brokerage'}
        </button>
      </div>
      {error && <p className="brokerage-page__error">{error}</p>}

      {connections === null && (
        <div className="brokerage-cards">
          <Skeleton width="180px" height="52px" />
        </div>
      )}

      {hasConnections && (
        <div className="brokerage-cards">
          {connections.map((connection) => {
            const name = connection.brokerage_name ?? 'Unknown brokerage'
            return (
              <div key={connection.id} className="brokerage-card">
                <div className="brokerage-card__logo">
                  <BrokerageLogo domain={connection.brokerage_domain} name={name} />
                </div>
                <div className="brokerage-card__info">
                  <span className="brokerage-card__name">{name}</span>
                  <span className={`brokerage-card__status brokerage-card__status--${connection.status}`}>
                    {connection.status}
                  </span>
                </div>
                <button
                  type="button"
                  className="brokerage-card__remove"
                  onClick={() => handleDisconnect(connection.id)}
                  aria-label={`Disconnect ${name}`}
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>
      )}

      {connections?.length === 0 && <p className="brokerage-page__empty">No brokerages connected yet.</p>}

      {hasConnections && <PortfolioOverview portfolio={portfolio} connections={connections} updatedAt={updatedAt} />}
    </div>
  )
}
