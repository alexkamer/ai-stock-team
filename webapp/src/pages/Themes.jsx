import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api/client'
import ThemePerformanceChart from '../components/ThemePerformanceChart'
import '../components/ToolCallPill.css'
import './StockTeam.css'
import './Scan.css'
import './Themes.css'

const RISK_LABEL = { lower: 'Lower risk', moderate: 'Moderate risk', higher: 'Higher risk' }

function RiskBadge({ level }) {
  if (!level) return null
  return <span className={`risk-badge risk-badge--${level}`}>{RISK_LABEL[level] ?? level}</span>
}

function ThemeCard({ theme, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`card themes__card themes__card--${theme.risk_level}${selected ? ' themes__card--selected' : ''}`}
      onClick={() => onSelect(theme.key)}
    >
      <h3>{theme.name}</h3>
      <p>{theme.description}</p>
      <RiskBadge level={theme.risk_level} />
    </button>
  )
}

function PriceChangeCell({ pick }) {
  if (pick.price_at_buy == null) {
    return <span className="themes__price-detail">—</span>
  }
  const direction = pick.change_percent > 0 ? 'up' : pick.change_percent < 0 ? 'down' : 'flat'
  return (
    <div className="themes__price-cell">
      {pick.current_price != null ? (
        <span className={`themes__price-change themes__price-change--${direction}`}>
          {pick.change_percent > 0 ? '+' : ''}
          {pick.change_percent.toFixed(2)}%
        </span>
      ) : (
        <span className="themes__price-detail">—</span>
      )}
      <span className="themes__price-detail">
        ${pick.price_at_buy.toFixed(2)}
        {pick.current_price != null ? ` → $${pick.current_price.toFixed(2)}` : ''}
      </span>
    </div>
  )
}

/** Dollar-weighted total return across all picks with a known price_at_buy
 * and current_price - picks missing either are excluded from both totals
 * so they don't drag it toward zero. */
function totalSinceBuy(picks) {
  let invested = 0
  let current = 0
  for (const pick of picks) {
    if (pick.price_at_buy == null || pick.current_price == null) continue
    invested += pick.dollar_amount
    current += pick.dollar_amount * (pick.current_price / pick.price_at_buy)
  }
  if (invested === 0) return null
  return { invested, current, changePercent: ((current - invested) / invested) * 100 }
}

function TotalSinceBuyBanner({ picks }) {
  const totals = totalSinceBuy(picks)
  if (!totals) return null
  const { invested, current, changePercent } = totals
  const direction = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'flat'
  return (
    <div className={`themes__total-banner themes__total-banner--${direction}`}>
      <span className="themes__total-label">Since buy</span>
      <span className="themes__total-change">
        {changePercent > 0 ? '+' : ''}
        {changePercent.toFixed(2)}%
      </span>
      <span className="themes__total-detail">
        ${invested.toFixed(2)} → ${current.toFixed(2)}
      </span>
    </div>
  )
}

function FilingsRelevance({ relevance }) {
  if (!relevance) return null
  return (
    <p className="themes__filings-relevance" title={relevance.rationale}>
      <span className="themes__filings-relevance-label">
        Why it's in this theme ({Math.round(relevance.relevance_score * 100)}% relevance):
      </span>{' '}
      {relevance.rationale}
    </p>
  )
}

/** weight_percent/price_at_buy never change with the amount typed in - only
 * dollar_amount/shares scale, so this is a pure client-side derivation, not
 * a fetch, every time `amount` changes. */
function applyAmount(picks, amount) {
  return picks.map((pick) => {
    const dollar_amount = amount * (pick.weight_percent / 100)
    const priceForShares = pick.current_price ?? pick.price_at_buy
    return { ...pick, dollar_amount, shares: priceForShares ? dollar_amount / priceForShares : 0 }
  })
}

function ThemeMeta({ suggestion }) {
  const stamp = suggestion.promoted_at ?? suggestion.generated_at
  return (
    <div className="themes__meta">
      <p className="themes__summary">{suggestion.summary}</p>
      <p className="themes__generated-label">
        Live since {new Date(stamp).toLocaleString()}
        {suggestion.candidate && ' · a newer version is pending above'}
      </p>
    </div>
  )
}

function AllocationTable({ suggestion, amount, filingsRelevance }) {
  const picks = applyAmount(suggestion.picks, amount)
  // Relative to the largest pick in *this* basket, not a literal 0-100%
  // scale - every theme is capped at _MAX_WEIGHT_PERCENT=35 server-side
  // (agents/theme_builder.py), so a flat 0-100% scale renders every bar
  // as a near-invisible sliver.
  const maxWeight = Math.max(...picks.map((p) => p.weight_percent))
  return (
    <>
      <ThemeMeta suggestion={suggestion} />
      <TotalSinceBuyBanner picks={picks} />
      <div className="card scan__table-card">
        <table className="scan__table themes__table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Weight</th>
              <th>Since buy</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((pick) => (
              <tr key={pick.ticker}>
                <td>
                  <div className="themes__ticker-cell">
                    <span className="themes__ticker">{pick.ticker}</span>
                    <span className="themes__rationale">{pick.rationale}</span>
                    <FilingsRelevance relevance={filingsRelevance?.[pick.ticker]} />
                  </div>
                </td>
                <td className="num">
                  <div className="themes__weight-cell">
                    <span className="themes__weight-bar">
                      <span
                        className="themes__weight-bar-fill"
                        style={{ width: `${(pick.weight_percent / maxWeight) * 100}%` }}
                      />
                    </span>
                    {pick.weight_percent.toFixed(1)}%
                  </div>
                </td>
                <td className="num">
                  <PriceChangeCell pick={pick} />
                </td>
                <td className="num">
                  <div className="themes__amount-cell">
                    <span>${pick.dollar_amount.toFixed(2)}</span>
                    <span className="themes__shares">{pick.shares.toFixed(4)} sh</span>
                  </div>
                </td>
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

function CandidateBanner({ candidate, onUpdate, updating }) {
  if (!candidate) return null
  const { added, removed, reweighted, quality_delta } = candidate
  const hasChanges = added.length || removed.length || reweighted.length
  if (!hasChanges) return null
  return (
    <div className="card themes__candidate-banner">
      <div className="themes__candidate-header">
        <strong>An updated version of this theme is available</strong>
        <button type="button" className="scan__run" onClick={onUpdate} disabled={updating}>
          {updating ? 'Updating…' : 'Update theme'}
        </button>
      </div>
      <p className="themes__generated-label">Generated {new Date(candidate.generated_at).toLocaleString()}</p>
      <p className="themes__summary">{candidate.summary}</p>
      {quality_delta != null && (
        <p className="themes__candidate-quality">
          Selection quality {quality_delta > 0 ? 'improved' : 'changed'} by {quality_delta > 0 ? '+' : ''}
          {(quality_delta * 100).toFixed(1)} points (a proxy for how central the theme is to each pick's business,
          not a performance guarantee).
        </p>
      )}
      <div className="themes__candidate-diff">
        {added.length > 0 && (
          <div className="themes__candidate-diff-group">
            <span className="themes__candidate-diff-group-label">Adding</span>
            <ul className="themes__candidate-diff-chips">
              {added.map((ticker) => (
                <li key={`add-${ticker}`} className="themes__candidate-diff-add">
                  {ticker}
                </li>
              ))}
            </ul>
          </div>
        )}
        {removed.length > 0 && (
          <div className="themes__candidate-diff-group">
            <span className="themes__candidate-diff-group-label">Dropping</span>
            <ul className="themes__candidate-diff-chips">
              {removed.map((ticker) => (
                <li key={`rm-${ticker}`} className="themes__candidate-diff-remove">
                  {ticker}
                </li>
              ))}
            </ul>
          </div>
        )}
        {reweighted.length > 0 && (
          <div className="themes__candidate-diff-group">
            <span className="themes__candidate-diff-group-label">Reweighting</span>
            <ul className="themes__candidate-diff-chips">
              {reweighted.map((r) => (
                <li key={`rw-${r.ticker}`} className="themes__candidate-diff-reweight">
                  {r.ticker} {r.from.toFixed(1)}%→{r.to.toFixed(1)}%
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Themes() {
  const [themes, setThemes] = useState([])
  const [selectedKey, setSelectedKey] = useState(null)
  const [amount, setAmount] = useState('5000')
  const [suggestion, setSuggestion] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [performanceLoading, setPerformanceLoading] = useState(false)
  const [filingsRelevance, setFilingsRelevance] = useState(null)
  const [notReady, setNotReady] = useState(false)
  const [error, setError] = useState(null)
  const [updating, setUpdating] = useState(false)

  useEffect(() => {
    getJSON('/themes').then(setThemes).catch(() => {})
  }, [])

  function loadPerformance(key) {
    setPerformanceLoading(true)
    getJSON(`/themes/${key}/performance`)
      .then(setPerformance)
      .catch(() => setPerformance(null))
      .finally(() => setPerformanceLoading(false))
  }

  function selectTheme(key) {
    setSelectedKey(key)
    setSuggestion(null)
    setPerformance(null)
    setNotReady(false)
    setError(null)
    getJSON(`/themes/${key}/suggestion`)
      .then(setSuggestion)
      .catch((e) => (e.status === 404 ? setNotReady(true) : setError(e.message)))
    getJSON(`/themes/${key}/filings-relevance`).then(setFilingsRelevance).catch(() => setFilingsRelevance(null))
    loadPerformance(key)
  }

  function updateTheme() {
    if (!selectedKey) return
    setUpdating(true)
    postJSON(`/themes/${selectedKey}/suggestion/promote`)
      .then(() => getJSON(`/themes/${selectedKey}/suggestion`))
      .then(setSuggestion)
      .then(() => loadPerformance(selectedKey))
      .catch((e) => setError(e.message))
      .finally(() => setUpdating(false))
  }

  const selectedTheme = themes.find((t) => t.key === selectedKey)
  const parsedAmount = Number(amount) || 0

  return (
    <div className="scan themes">
      <div className="scan__header">
        <div>
          <h2>Themes</h2>
          <p className="scan__subtitle">
            Pick a theme to see its suggested allocation - the same ranked basket every visitor sees, refreshed on a
            schedule rather than rebuilt per visit. Type an amount to see it sized in dollars.
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
        <div className="card themes__build">
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
          </div>

          {notReady && (
            <p className="scan__empty">
              A suggested allocation for {selectedTheme.name} hasn't been generated yet - check back soon.
            </p>
          )}

          {suggestion && (
            <>
              <CandidateBanner candidate={suggestion.candidate} onUpdate={updateTheme} updating={updating} />
              <div className="card">
                <ThemePerformanceChart
                  points={performance?.points}
                  updates={performance?.updates}
                  loading={performanceLoading}
                />
              </div>
              <AllocationTable suggestion={suggestion} amount={parsedAmount} filingsRelevance={filingsRelevance} />
            </>
          )}
        </div>
      )}
    </div>
  )
}
