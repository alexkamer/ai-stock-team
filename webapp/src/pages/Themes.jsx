import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON } from '../api/client'
import './StockTeam.css'
import './Scan.css'
import './Themes.css'

const RISK_LABEL = { lower: 'Lower risk', moderate: 'Moderate risk', higher: 'Higher risk' }

function RiskBadge({ level }) {
  if (!level) return null
  return <span className={`risk-badge risk-badge--${level}`}>{RISK_LABEL[level] ?? level}</span>
}

/** Dollar-weighted since-buy return - weight_percent stands in for a dollar
 * amount here (same ratios, no amount typed in on this list page) so this
 * is the same formula ThemeDetail.jsx uses to total up its allocation
 * table, just without a concrete dollar figure. */
function sinceBuyPercent(picks) {
  let invested = 0
  let current = 0
  for (const pick of picks) {
    if (pick.price_at_buy == null || pick.current_price == null) continue
    invested += pick.weight_percent
    current += pick.weight_percent * (pick.current_price / pick.price_at_buy)
  }
  if (invested === 0) return null
  return ((current - invested) / invested) * 100
}

function hasPendingUpdate(candidate) {
  if (!candidate) return false
  return candidate.added.length > 0 || candidate.removed.length > 0 || candidate.reweighted.length > 0
}

/** Compact "3d ago"/"2h ago" - a full timestamp is too wide for a list
 * row, unlike the detail page which has room for `toLocaleString()`. */
function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 60) return `${Math.max(minutes, 0)}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  return `${months}mo ago`
}

// Every row renders the same fixed set of grid cells, in the same order,
// even when a cell has nothing to show (e.g. no suggestion yet) - that's
// what keeps the columns aligned across rows instead of shifting to fit
// each row's content (see .themes__row's grid-template-columns).
function ThemeRow({ theme, suggestion }) {
  const changePercent = suggestion ? sinceBuyPercent(suggestion.picks) : null
  const direction = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'flat'
  const stamp = suggestion ? suggestion.promoted_at ?? suggestion.generated_at : null
  const updateAvailable = suggestion && hasPendingUpdate(suggestion.candidate)

  return (
    <Link to={`/themes/${theme.key}`} className={`card themes__row themes__row--${theme.risk_level}`}>
      <div className="themes__row-text">
        <h3>{theme.name}</h3>
        <p>{theme.description}</p>
      </div>
      <span className={`themes__row-change themes__row-change--${direction}`}>
        {changePercent != null ? `${changePercent > 0 ? '+' : ''}${changePercent.toFixed(2)}%` : '—'}
      </span>
      <span className="themes__row-updated">{stamp ? `Updated ${timeAgo(stamp)}` : suggestion === null ? 'Not ready yet' : ''}</span>
      <span className={`themes__row-update-badge${updateAvailable ? '' : ' themes__row-update-badge--hidden'}`}>
        Update available
      </span>
      <RiskBadge level={theme.risk_level} />
    </Link>
  )
}

export default function Themes() {
  const [themes, setThemes] = useState([])
  const [suggestions, setSuggestions] = useState({})

  useEffect(() => {
    getJSON('/themes').then((loaded) => {
      setThemes(loaded)
      for (const theme of loaded) {
        getJSON(`/themes/${theme.key}/suggestion`)
          .then((suggestion) => setSuggestions((prev) => ({ ...prev, [theme.key]: suggestion })))
          .catch(() => setSuggestions((prev) => ({ ...prev, [theme.key]: null })))
      }
    })
  }, [])

  return (
    <div className="scan themes">
      <div className="scan__header">
        <div>
          <h2>Themes</h2>
          <p className="scan__subtitle">
            Pick a theme to see its suggested allocation - the same ranked basket every visitor sees, refreshed on a
            schedule rather than rebuilt per visit.
          </p>
        </div>
      </div>

      <section className="themes__list">
        {themes.map((theme) => (
          <ThemeRow key={theme.key} theme={theme} suggestion={suggestions[theme.key]} />
        ))}
      </section>
    </div>
  )
}
