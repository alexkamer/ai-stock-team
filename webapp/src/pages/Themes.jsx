import { useEffect, useRef, useState } from 'react'
import { getJSON, streamSSE } from '../api/client'
import '../components/ToolCallPill.css'
import './StockTeam.css'
import './Scan.css'
import './Themes.css'

const RISK_LABEL = { lower: 'Lower risk', moderate: 'Moderate risk', higher: 'Higher risk' }
const METHOD_LABEL = { formula: 'Formula', ai_team: 'AI Team' }

function RiskBadge({ level }) {
  if (!level) return null
  return <span className={`risk-badge risk-badge--${level}`}>{RISK_LABEL[level] ?? level}</span>
}

function MethodBadge({ method }) {
  if (!method) return null
  return <span className={`method-badge method-badge--${method}`}>{METHOD_LABEL[method] ?? method}</span>
}

function ThemeCard({ theme, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`card themes__card${selected ? ' themes__card--selected' : ''}`}
      onClick={() => onSelect(theme.key)}
    >
      <div className="themes__card-header">
        <h3>{theme.name}</h3>
        <RiskBadge level={theme.risk_level} />
      </div>
      <p>{theme.description}</p>
    </button>
  )
}

function AllocationTable({ allocation }) {
  if (!allocation.picks.length) {
    return <p className="scan__empty">{allocation.summary}</p>
  }
  return (
    <>
      <p className="themes__summary">{allocation.summary}</p>
      <div className="card scan__table-card">
        <table className="scan__table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Weight</th>
              <th>Amount</th>
              <th>Shares</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {allocation.picks.map((pick) => (
              <tr key={pick.ticker}>
                <td>{pick.ticker}</td>
                <td className="num themes__weight-cell">
                  <span className="themes__weight-bar">
                    <span className="themes__weight-bar-fill" style={{ width: `${pick.weight_percent}%` }} />
                  </span>
                  {pick.weight_percent.toFixed(1)}%
                </td>
                <td className="num">${pick.dollar_amount.toFixed(2)}</td>
                <td className="num">{pick.shares.toFixed(4)}</td>
                <td className="themes__rationale">{pick.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="themes__disclaimer">
        Share counts are illustrative and fractional - whether you can actually buy fractional shares depends on
        your broker. This isn't investment advice.
      </p>
    </>
  )
}

/** Groups history entries (already newest-first from the API) by theme -
 * each group's own entries stay newest-first, and groups are ordered by
 * their most recent run, since the first occurrence of a theme_key in a
 * newest-first list is that theme's most recent run. */
function groupHistoryByTheme(history) {
  const groups = new Map()
  for (const entry of history) {
    if (!groups.has(entry.theme_key)) groups.set(entry.theme_key, [])
    groups.get(entry.theme_key).push(entry)
  }
  return Array.from(groups.entries()).map(([themeKey, entries]) => ({ themeKey, entries }))
}

export default function Themes() {
  const [themes, setThemes] = useState([])
  const [selectedKey, setSelectedKey] = useState(null)
  const [amount, setAmount] = useState('5000')
  const [candidates, setCandidates] = useState(null)
  const [formulaAllocation, setFormulaAllocation] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState([])
  const [expandedThemes, setExpandedThemes] = useState(() => new Set())
  const controllerRef = useRef(null)
  const buildRef = useRef(null)

  useEffect(() => {
    getJSON('/themes').then(setThemes).catch(() => {})
    getJSON('/themes/history').then(setHistory).catch(() => {})
  }, [])

  function selectTheme(key) {
    setSelectedKey(key)
    setCandidates(null)
    setFormulaAllocation(null)
    setError(null)
    controllerRef.current?.abort()
  }

  function runBuild() {
    const parsedAmount = Number(amount)
    if (!selectedKey || !parsedAmount || parsedAmount <= 0) return

    setCandidates(null)
    setFormulaAllocation(null)
    setError(null)
    setRunning(true)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    streamSSE(`/themes/${selectedKey}/build?amount=${parsedAmount}`, {
      signal: controller.signal,
      onEvent: (eventName, data) => {
        if (eventName === 'candidates') {
          setCandidates(data.tickers)
        } else if (eventName === 'formula_allocation') {
          setFormulaAllocation(data)
          getJSON('/themes/history').then(setHistory).catch(() => {})
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

  function viewPastAllocation(entry) {
    controllerRef.current?.abort()
    setSelectedKey(entry.theme_key)
    setAmount(String(entry.amount))
    setCandidates(null)
    setError(null)
    setFormulaAllocation(entry)
    buildRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function toggleThemeHistory(themeKey) {
    setExpandedThemes((prev) => {
      const next = new Set(prev)
      if (next.has(themeKey)) next.delete(themeKey)
      else next.add(themeKey)
      return next
    })
  }

  const selectedTheme = themes.find((t) => t.key === selectedKey)
  const historyGroups = groupHistoryByTheme(history)

  return (
    <div className="scan themes">
      <div className="scan__header">
        <div>
          <h2>Themes</h2>
          <p className="scan__subtitle">
            Pick a theme, tell us how much you want to invest, and we'll rank its live ticker universe by
            momentum and market cap to size a basket - no AI vetting, just data, so it's instant.
          </p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <section className="themes__grid">
        {themes.map((theme) => (
          <ThemeCard key={theme.key} theme={theme} selected={theme.key === selectedKey} onSelect={selectTheme} />
        ))}
      </section>

      {selectedTheme && (
        <div ref={buildRef} className="card themes__build">
          <div className="themes__build-row">
            <label className="themes__amount-label">
              Amount to invest
              <span className="themes__amount-input">
                <span aria-hidden="true">$</span>
                <input
                  type="number"
                  min="1"
                  step="100"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </span>
            </label>
            <button type="button" className="scan__run" onClick={runBuild} disabled={running}>
              {running ? 'Building…' : formulaAllocation ? 'Rebuild' : `Build ${selectedTheme.name} portfolio`}
            </button>
          </div>

          {candidates && !formulaAllocation && (
            <span className="scan__count">Screened {candidates.length} tickers…</span>
          )}

          {formulaAllocation && <AllocationTable allocation={formulaAllocation} />}
        </div>
      )}

      {historyGroups.length > 0 && (
        <div className="themes__history">
          <h3>Past portfolios</h3>
          {historyGroups.map(({ themeKey, entries }) => {
            const theme = themes.find((t) => t.key === themeKey)
            const expanded = expandedThemes.has(themeKey)
            return (
              <div key={themeKey} className="card themes__history-group">
                <button
                  type="button"
                  className="themes__history-group-header"
                  aria-expanded={expanded}
                  onClick={() => toggleThemeHistory(themeKey)}
                >
                  <span className={`themes__history-chevron${expanded ? ' themes__history-chevron--open' : ''}`}>
                    &#9656;
                  </span>
                  <strong>{theme?.name ?? themeKey}</strong>
                  <span className="scan__count">
                    {entries.length} run{entries.length === 1 ? '' : 's'} &middot; last{' '}
                    {new Date(entries[0].created_at).toLocaleDateString()}
                  </span>
                </button>

                {expanded && (
                  <div className="themes__history-entries">
                    {entries.map((entry, i) => (
                      <button
                        key={i}
                        type="button"
                        className="themes__history-card"
                        onClick={() => viewPastAllocation(entry)}
                      >
                        <div className="themes__history-header">
                          <MethodBadge method={entry.method} />
                          <span className="scan__count">
                            ${entry.amount.toLocaleString()} &middot; {new Date(entry.created_at).toLocaleDateString()}
                          </span>
                        </div>
                        <p className="themes__summary">{entry.summary}</p>
                        <p className="themes__history-tickers">{entry.picks.map((p) => p.ticker).join(', ')}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
