import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { streamSSE } from '../api/client'
import '../components/ToolCallPill.css'
import './StockTeam.css'
import './Scan.css'

const VERDICT_LABEL = { buy: 'Buy', hold: 'Hold', sell: 'Sell' }
const HORIZON_LABEL = { '1w': '1 week', '1mo': '1 month', '3mo': '3 months' }

function VerdictBadge({ verdict }) {
  if (!verdict) return null
  return <span className={`verdict-badge verdict-badge--${verdict}`}>{VERDICT_LABEL[verdict]}</span>
}

function ScanRow({ ticker, result }) {
  return (
    <tr className={result?.error ? 'scan__row--error' : ''}>
      <td>
        <Link to={`/tickers/${ticker}/team`}>{ticker}</Link>
      </td>
      <td>
        {!result ? (
          <span className="scan__pending">
            <span className="tool-pill__spinner" aria-hidden="true" />
            Analyzing…
          </span>
        ) : result.error ? (
          <span className="scan__error-text">{result.error}</span>
        ) : (
          <VerdictBadge verdict={result.verdict} />
        )}
      </td>
      <td className="num">
        {result && !result.error && result.predicted_price != null
          ? `$${result.predicted_price.toFixed(2)} in ${HORIZON_LABEL[result.predicted_horizon] ?? result.predicted_horizon}`
          : '—'}
      </td>
      <td>{result && !result.error && result.reused && <span className="scan__reused">already called today</span>}</td>
    </tr>
  )
}

export default function Scan() {
  const [candidates, setCandidates] = useState(null)
  const [results, setResults] = useState({})
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  const [buyOnly, setBuyOnly] = useState(false)
  const controllerRef = useRef(null)

  function runScan() {
    setCandidates(null)
    setResults({})
    setError(null)
    setRunning(true)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    streamSSE('/tickers/team-scan', {
      signal: controller.signal,
      onEvent: (eventName, data) => {
        if (eventName === 'candidates') {
          setCandidates(data.tickers)
        } else if (eventName === 'result') {
          setResults((prev) => ({ ...prev, [data.ticker]: data }))
        } else if (eventName === 'error') {
          setError(data.detail)
        }
      },
    })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message)
      })
      .finally(() => setRunning(false))
  }

  const visibleCandidates = (candidates ?? []).filter((ticker) => {
    if (!buyOnly) return true
    return results[ticker]?.verdict === 'buy'
  })

  return (
    <div className="scan">
      <div className="scan__header">
        <div>
          <h2>Buy scan</h2>
          <p className="scan__subtitle">
            Runs the full Stock Team analysis over today's most-active, top-gaining, and trending tickers, so you
            can find candidates outside your own watchlist instead of checking one ticker at a time.
          </p>
        </div>
        <button type="button" className="scan__run" onClick={runScan} disabled={running}>
          {running ? 'Scanning…' : candidates ? 'Run again' : 'Run scan'}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {candidates && (
        <>
          <div className="scan__controls">
            <label className="scan__filter">
              <input type="checkbox" checked={buyOnly} onChange={(e) => setBuyOnly(e.target.checked)} />
              Buy only
            </label>
            <span className="scan__count">
              {Object.keys(results).length} / {candidates.length} analyzed
            </span>
          </div>

          <div className="card scan__table-card">
            <table className="scan__table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Verdict</th>
                  <th>Target</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {visibleCandidates.map((ticker) => (
                  <ScanRow key={ticker} ticker={ticker} result={results[ticker]} />
                ))}
              </tbody>
            </table>
            {visibleCandidates.length === 0 && (
              <p className="scan__empty">No buy verdicts yet{running ? ' - still scanning…' : '.'}</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
