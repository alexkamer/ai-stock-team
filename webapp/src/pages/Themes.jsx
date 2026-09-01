import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getJSON } from '../api/client'
import { parseServerDate } from '../lib/serverDate'
import './StockTeam.css'
import './Scan.css'
import './Themes.css'

const RISK_LEVEL_LABEL = { low: 'Low', moderate: 'Moderate', high: 'High' }

function LevelPill({ level }) {
  if (!level) return <span className="themes__summary-cell-muted">—</span>
  return (
    <span className={`themes__risk-metric-level themes__risk-metric-level--${level}`}>
      {RISK_LEVEL_LABEL[level] ?? level}
    </span>
  )
}

function PercentCell({ value }) {
  if (value == null) return <span className="themes__summary-cell-muted">—</span>
  const direction = value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
  return (
    <span className={`themes__summary-percent themes__summary-percent--${direction}`}>
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}%
    </span>
  )
}

function formatInceptionDate(dateOnlyIso) {
  if (!dateOnlyIso) return null
  return new Date(`${dateOnlyIso}T00:00:00`).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}

// One fixed set of cells per row, in the same order, even when a theme
// has no summary yet - keeps every column aligned the same way
// Themes.css's row grid used to (see the git history for that layout);
// here it's a real <table> so alignment comes from the columns
// themselves.
function ThemeRow({ theme, summary, summariesLoading }) {
  const navigate = useNavigate()
  const previewTickers = summary?.preview_tickers ?? []
  const hasMore = (summary?.stock_count ?? 0) > previewTickers.length

  return (
    <tr className="themes__summary-row" onClick={() => navigate(`/themes/${theme.key}`)}>
      <td>
        <div className="themes__summary-name-cell">
          <span className="themes__summary-name">{theme.name}</span>
          <span className="themes__summary-tickers">
            {summary ? (
              <>
                {summary.stock_count} Stock{summary.stock_count === 1 ? '' : 's'}
                {previewTickers.length > 0 && ` - ${previewTickers.join(', ')}${hasMore ? '...' : ''}`}
              </>
            ) : summariesLoading ? (
              'Loading…'
            ) : (
              'Not ready yet'
            )}
          </span>
        </div>
      </td>
      <td className="num">
        <PercentCell value={summary?.day_change_percent} />
      </td>
      <td className="num">
        <PercentCell value={summary?.one_month_return_percent} />
      </td>
      <td className="num">
        <PercentCell value={summary?.one_year_return_percent} />
      </td>
      <td className="num">
        <div className="themes__summary-inception-cell">
          <PercentCell value={summary?.since_inception_percent} />
          {summary?.inception_date && (
            <span className="themes__summary-inception-date">{formatInceptionDate(summary.inception_date)}</span>
          )}
        </div>
      </td>
      <td className="num">
        <LevelPill level={summary?.volatility_label} />
      </td>
      <td className="num">
        <LevelPill level={summary?.valuation_label} />
      </td>
    </tr>
  )
}

export default function Themes() {
  const [themes, setThemes] = useState([])
  const [summaries, setSummaries] = useState({})
  const [summariesLoading, setSummariesLoading] = useState(true)
  const [summariesError, setSummariesError] = useState(false)

  useEffect(() => {
    getJSON('/themes').then(setThemes).catch(() => {})
    getJSON('/themes/summary')
      .then((rows) => setSummaries(Object.fromEntries(rows.map((row) => [row.key, row]))))
      .catch(() => setSummariesError(true))
      .finally(() => setSummariesLoading(false))
  }, [])

  // Every row's data was refreshed in the same scheduled pass (see
  // agents/refresh_themes.py --summary-only), so any row's updated_at
  // represents "when the whole snapshot below was last refreshed" - not
  // a per-row freshness indicator.
  const latestUpdatedAt = Object.values(summaries)
    .map((s) => s.updated_at)
    .filter(Boolean)
    .sort()
    .at(-1)

  return (
    <div className="scan themes">
      <div className="scan__header">
        <div>
          <h2>Themes</h2>
          <p className="scan__subtitle">
            The same ranked basket every visitor sees, refreshed on a schedule rather than rebuilt per visit. Click a
            theme for its full allocation, performance, and investment case.
          </p>
        </div>
      </div>

      {latestUpdatedAt && (
        <p className="themes__summary-updated-note">
          Market data as of {parseServerDate(latestUpdatedAt).toLocaleString()}
        </p>
      )}
      {summariesError && (
        <div className="error-banner">
          Couldn't load market data for the themes below - theme names and descriptions still work, try refreshing in
          a bit for the rest.
        </div>
      )}

      <div className="card scan__table-card themes__summary-table-card">
        <table className="scan__table themes__summary-table">
          <thead>
            <tr>
              <th>Theme</th>
              <th>Day Change</th>
              <th>1-Month Return</th>
              <th>1-Year Return</th>
              <th>Since Inception</th>
              <th>Volatility</th>
              <th>Valuation</th>
            </tr>
          </thead>
          <tbody>
            {themes.map((theme) => (
              <ThemeRow key={theme.key} theme={theme} summary={summaries[theme.key]} summariesLoading={summariesLoading} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
