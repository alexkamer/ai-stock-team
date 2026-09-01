import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getJSON, postJSON } from '../api/client'
import { parseServerDate } from '../lib/serverDate'
import ThemePerformanceChart from '../components/ThemePerformanceChart'
import '../components/ToolCallPill.css'
import './StockTeam.css'
import './Scan.css'
import './Themes.css'

// Volatility/valuation replace the old static "HIGHER RISK" label with a
// number actually computed from this theme's current picks (see
// agents/theme_builder.py's _weighted_risk_metrics) - null while the
// suggestion is still loading, or if there wasn't enough data to compute
// one (e.g. every pick missing price history).
const RISK_LEVEL_LABEL = { low: 'Low', moderate: 'Moderate', high: 'High' }

function RiskMetric({ label, value, level }) {
  return (
    <span className="themes__risk-metric">
      <span className="themes__risk-metric-label">{label}</span>
      <span className="themes__risk-metric-value">{value}</span>
      {level && (
        <span className={`themes__risk-metric-level themes__risk-metric-level--${level}`}>
          {RISK_LEVEL_LABEL[level] ?? level}
        </span>
      )}
    </span>
  )
}

// Low/Moderate/High is relative to a fixed basket of large-cap stocks,
// not a fixed absolute cutoff (see agents/theme_builder.py's
// _benchmark_risk_metrics) - "High" means more volatile/expensive than a
// typical large-cap stock right now, not more than some hardcoded number.
function RiskMetrics({ suggestion }) {
  if (!suggestion) return null
  const { volatility, valuation, volatility_label, valuation_label } = suggestion
  return (
    <div className="themes__risk-metrics">
      <RiskMetric
        label="Volatility"
        value={volatility != null ? `${(volatility * 100).toFixed(1)}%` : '—'}
        level={volatility_label}
      />
      <RiskMetric
        label="Valuation (P/E)"
        value={valuation != null ? `${valuation.toFixed(1)}x` : '—'}
        level={valuation_label}
      />
    </div>
  )
}

function formatSimpleDate(dateOnlyIso) {
  return new Date(`${dateOnlyIso}T00:00:00`).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}

// inceptionDate comes from performance.updates[0] (a plain "YYYY-MM-DD" -
// the first version's own promoted_at.date()); lastUpdatedIso comes from
// suggestion.promoted_at/generated_at, a naive-UTC backend timestamp, so
// it needs parseServerDate first, unlike inceptionDate.
function AboutTheme({ theme, inceptionDate, lastUpdatedIso }) {
  if (!theme) return null
  return (
    <div className="card themes__about">
      <h4>About {theme.name}</h4>
      <div className="themes__about-meta">
        {inceptionDate && <span>Inception date: {formatSimpleDate(inceptionDate)}</span>}
        {lastUpdatedIso && <span>Basket last updated: {parseServerDate(lastUpdatedIso).toLocaleDateString()}</span>}
      </div>
      {(theme.about ?? theme.description).split('\n\n').map((paragraph, i) => (
        <p key={i}>{paragraph}</p>
      ))}
      <p className="themes__disclaimer">
        This is a summary of the theme's investment case, not personalized investment advice.
      </p>
    </div>
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
        Live since {parseServerDate(stamp).toLocaleString()}
        {suggestion.candidate && ' · a newer version is pending above'}
      </p>
    </div>
  )
}

// Sorted by combined weight, heaviest sector first - the same "what
// dominates this basket" question the weight bars answer per-ticker,
// one level up.
function groupBySector(picks) {
  const bySector = new Map()
  for (const pick of picks) {
    const sector = pick.sector || 'Other'
    if (!bySector.has(sector)) bySector.set(sector, [])
    bySector.get(sector).push(pick)
  }
  return [...bySector.entries()]
    .map(([sector, sectorPicks]) => ({
      sector,
      picks: sectorPicks,
      weight: sectorPicks.reduce((sum, p) => sum + p.weight_percent, 0),
    }))
    .sort((a, b) => b.weight - a.weight)
}

function PickRow({ pick, filingsRelevance, maxWeight }) {
  return (
    <tr>
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
            <span className="themes__weight-bar-fill" style={{ width: `${(pick.weight_percent / maxWeight) * 100}%` }} />
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
  )
}

function SectorExpander({ group, filingsRelevance, maxWeight }) {
  const totals = totalSinceBuy(group.picks)
  const changePercent = totals?.changePercent ?? null
  const direction = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'flat'
  return (
    <details className="card themes__sector" open>
      <summary className="themes__sector-summary">
        <span className="themes__sector-name">{group.sector}</span>
        <span className="themes__sector-count">{group.picks.length} stock{group.picks.length === 1 ? '' : 's'}</span>
        <span className="themes__sector-weight num">{group.weight.toFixed(1)}%</span>
        <span className={`themes__sector-return num themes__sector-return--${direction}`}>
          {changePercent != null ? `${changePercent > 0 ? '+' : ''}${changePercent.toFixed(2)}%` : '—'}
        </span>
      </summary>
      <div className="themes__sector-table-wrap">
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
            {group.picks.map((pick) => (
              <PickRow key={pick.ticker} pick={pick} filingsRelevance={filingsRelevance} maxWeight={maxWeight} />
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

function AllocationTable({ suggestion, amount, filingsRelevance, themeName }) {
  const picks = applyAmount(suggestion.picks, amount)
  // Relative to the largest pick in *this* basket, not a literal 0-100%
  // scale - every theme is capped at _MAX_WEIGHT_PERCENT=35 server-side
  // (agents/theme_builder.py), so a flat 0-100% scale renders every bar
  // as a near-invisible sliver.
  const maxWeight = Math.max(...picks.map((p) => p.weight_percent))
  const sectorGroups = groupBySector(picks)
  return (
    <>
      <ThemeMeta suggestion={suggestion} />
      <TotalSinceBuyBanner picks={picks} />
      <h4 className="themes__table-header">
        Stocks in {themeName} ({picks.length})
      </h4>
      <div className="themes__sectors">
        {sectorGroups.map((group) => (
          <SectorExpander key={group.sector} group={group} filingsRelevance={filingsRelevance} maxWeight={maxWeight} />
        ))}
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
      <p className="themes__generated-label">Generated {parseServerDate(candidate.generated_at).toLocaleString()}</p>
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

export default function ThemeDetail() {
  const { themeKey } = useParams()
  const [theme, setTheme] = useState(null)
  const [amount, setAmount] = useState('5000')
  const [suggestion, setSuggestion] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [performanceLoading, setPerformanceLoading] = useState(false)
  const [filingsRelevance, setFilingsRelevance] = useState(null)
  const [notReady, setNotReady] = useState(false)
  const [error, setError] = useState(null)
  const [updating, setUpdating] = useState(false)

  function loadPerformance(key) {
    setPerformanceLoading(true)
    getJSON(`/themes/${key}/performance`)
      .then(setPerformance)
      .catch(() => setPerformance(null))
      .finally(() => setPerformanceLoading(false))
  }

  useEffect(() => {
    setTheme(null)
    setSuggestion(null)
    setPerformance(null)
    setNotReady(false)
    setError(null)

    getJSON('/themes')
      .then((themes) => setTheme(themes.find((t) => t.key === themeKey) ?? null))
      .catch(() => {})
    getJSON(`/themes/${themeKey}/suggestion`)
      .then(setSuggestion)
      .catch((e) => (e.status === 404 ? setNotReady(true) : setError(e.message)))
    getJSON(`/themes/${themeKey}/filings-relevance`).then(setFilingsRelevance).catch(() => setFilingsRelevance(null))
    loadPerformance(themeKey)
  }, [themeKey])

  function updateTheme() {
    setUpdating(true)
    postJSON(`/themes/${themeKey}/suggestion/promote`)
      .then(() => getJSON(`/themes/${themeKey}/suggestion`))
      .then(setSuggestion)
      .then(() => loadPerformance(themeKey))
      .catch((e) => setError(e.message))
      .finally(() => setUpdating(false))
  }

  const parsedAmount = Number(amount) || 0

  return (
    <div className="scan themes">
      <div className="scan__header">
        <div>
          <Link to="/themes" className="themes__back-link">
            ← All themes
          </Link>
          <h2>{theme?.name ?? themeKey}</h2>
          {theme && <p className="scan__subtitle">{theme.description}</p>}
        </div>
        <RiskMetrics suggestion={suggestion} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <ThemePerformanceChart points={performance?.points} updates={performance?.updates} loading={performanceLoading} />
      </div>

      <AboutTheme
        theme={theme}
        inceptionDate={performance?.updates?.[0]?.date}
        lastUpdatedIso={suggestion?.promoted_at ?? suggestion?.generated_at}
      />

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
            A suggested allocation for {theme?.name ?? 'this theme'} hasn't been generated yet - check back soon.
          </p>
        )}

        {suggestion && (
          <>
            <CandidateBanner candidate={suggestion.candidate} onUpdate={updateTheme} updating={updating} />
            <AllocationTable
              suggestion={suggestion}
              amount={parsedAmount}
              filingsRelevance={filingsRelevance}
              themeName={theme?.name ?? themeKey}
            />
          </>
        )}
      </div>
    </div>
  )
}
