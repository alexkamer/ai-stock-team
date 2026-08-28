import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getJSON, streamSSE } from '../api/client'
import { specialistStatsCache } from '../api/specialistStatsCache'
import { teamAnalysisCache } from '../api/teamAnalysisCache'
import TrackRecord from './TrackRecord'
import '../components/ToolCallPill.css'
import './StockTeam.css'

const VERDICT_LABEL = { buy: 'Buy', hold: 'Hold', sell: 'Sell' }
const HORIZON_LABEL = { '1w': '1 week', '1mo': '1 month', '3mo': '3 months' }

// Below this many scored calls, a hit rate is mostly noise - shown as "not
// enough data yet" instead of a misleadingly precise-looking percentage.
const MIN_SCORED_CALLS_FOR_ACCURACY = 5

// Six specialists now fit a clean 3x2 grid (see StockTeam.css) - no more
// awkward single card stranded alone in its own row, so there's no need for
// the compact/wide split the 5-specialist layout used.
const SPECIALISTS = [
  { tool: 'get_fundamentals', label: 'Fundamentals', description: 'Price, market cap, P/E' },
  { tool: 'get_technicals', label: 'Technicals', description: 'Momentum & trend' },
  { tool: 'get_valuation', label: 'Valuation vs. Peers', description: 'Multiples vs. sector' },
  { tool: 'get_sentiment', label: 'Sentiment', description: 'Recent news tone' },
  { tool: 'get_risk', label: 'Risk / Macro', description: 'Volatility & downside risk' },
  { tool: 'get_portfolio_fit', label: 'Portfolio Fit', description: 'Given your holdings' },
]

function VerdictBadge({ verdict }) {
  if (!verdict) return null
  return <span className={`verdict-badge verdict-badge--${verdict}`}>{VERDICT_LABEL[verdict]}</span>
}

function SignalDot({ signal }) {
  return <span className={`signal-dot signal-dot--${signal}`} aria-hidden="true" />
}

function PriceTarget({ predictedPrice, predictedHorizon }) {
  if (predictedPrice == null) return null
  return (
    <span className="stock-team__target">
      Target ${predictedPrice.toFixed(2)} in {HORIZON_LABEL[predictedHorizon] ?? predictedHorizon}
    </span>
  )
}

function OwnershipNote({ ticker, isHeld }) {
  if (isHeld == null) return null
  return (
    <p className="stock-team__ownership-note">
      {isHeld
        ? `You currently hold ${ticker} — "Hold" here means keep the position as-is.`
        : `You don't currently own ${ticker} — "Hold" here means not compelling enough to buy right now, not an instruction to exit a position.`}
    </p>
  )
}

function SpecialistAccuracy({ stats }) {
  if (!stats || stats.scored_calls < MIN_SCORED_CALLS_FOR_ACCURACY) {
    return <span className="specialist-card__accuracy specialist-card__accuracy--pending">Not enough data yet</span>
  }
  return (
    <span className="specialist-card__accuracy">
      {stats.hit_rate_percent.toFixed(0)}% · {stats.scored_calls} calls
    </span>
  )
}

function SpecialistCard({ label, description, finding, stats }) {
  return (
    <div className={`card specialist-card${finding ? ' specialist-card--done' : ''}`}>
      <div className="specialist-card__header">
        <div className="specialist-card__heading">
          <span className="specialist-card__label">{label}</span>
          <span className="specialist-card__description">{description}</span>
        </div>
        <SpecialistAccuracy stats={stats} />
      </div>
      {finding ? (
        <>
          <div className="specialist-card__headline">
            <SignalDot signal={finding.signal} />
            {finding.headline}
          </div>
          <ul className="specialist-card__points">
            {finding.key_points.map((point, i) => (
              <li key={i}>{point}</li>
            ))}
          </ul>
        </>
      ) : (
        <div className="specialist-card__pending">
          <span className="tool-pill__spinner" aria-hidden="true" />
          Consulting…
        </div>
      )}
    </div>
  )
}

export default function StockTeam() {
  const { ticker } = useParams()
  const [findings, setFindings] = useState({})
  const [verdict, setVerdict] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0)
  const [specialistStats, setSpecialistStats] = useState({})
  const controllerRef = useRef(null)

  useEffect(() => {
    specialistStatsCache.promise ??= getJSON('/track-record/specialists').catch(() => ({ specialist_stats: {} }))
    specialistStatsCache.promise.then((data) => setSpecialistStats(data.specialist_stats ?? {}))
  }, [])

  const runAnalysis = (targetTicker) => {
    setFindings({})
    setVerdict(null)
    setError(null)
    setLoading(true)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    const runFindings = {}

    streamSSE(`/tickers/${targetTicker}/team`, {
      signal: controller.signal,
      onEvent: (eventName, data) => {
        if (eventName === 'tool_result') {
          runFindings[data.tool_name] = data.content
          setFindings((prev) => ({ ...prev, [data.tool_name]: data.content }))
        } else if (eventName === 'verdict') {
          setVerdict(data)
          teamAnalysisCache[targetTicker] = { findings: runFindings, verdict: data }
          setHistoryRefreshKey((k) => k + 1)
        } else if (eventName === 'error') {
          setError(data.detail)
        }
      },
    })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    const cached = teamAnalysisCache[ticker]
    if (cached) {
      setFindings(cached.findings)
      setVerdict(cached.verdict)
      setError(null)
      setLoading(false)
    } else {
      runAnalysis(ticker)
    }

    return () => controllerRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  if (error) return <div className="error-banner">{error}</div>

  return (
    <div className="stock-team">
      <div className="stock-team__subtitle-row">
        <p className="stock-team__subtitle">
          Six specialists weigh in independently, then a synthesizer renders a verdict.
        </p>
        <button
          type="button"
          className="stock-team__regenerate"
          onClick={() => runAnalysis(ticker)}
          disabled={loading}
        >
          {loading ? 'Analyzing…' : 'Regenerate'}
        </button>
      </div>

      <div className="stock-team__specialists">
        {SPECIALISTS.map((s) => (
          <SpecialistCard
            key={s.tool}
            label={s.label}
            description={s.description}
            finding={findings[s.tool]}
            stats={specialistStats[s.tool]}
          />
        ))}
      </div>

      <div className={`card stock-team__verdict${verdict ? ` stock-team__verdict--${verdict.verdict}` : ''}`}>
        <div className="stock-team__verdict-header">
          <span className="eyebrow">Synthesizer verdict</span>
          <div className="stock-team__verdict-header-right">
            <PriceTarget predictedPrice={verdict?.predicted_price} predictedHorizon={verdict?.predicted_horizon} />
            <VerdictBadge verdict={verdict?.verdict} />
          </div>
        </div>
        {verdict ? (
          <>
            <OwnershipNote ticker={ticker} isHeld={verdict.is_held} />
            <ul className="stock-team__factors">
              {verdict.key_factors.map((factor, i) => (
                <li key={i}>{factor}</li>
              ))}
            </ul>
            <p className="stock-team__reasoning">{verdict.reasoning}</p>
          </>
        ) : (
          <div className="specialist-card__pending">
            <span className="tool-pill__spinner" aria-hidden="true" />
            Weighing specialist findings…
          </div>
        )}
      </div>

      <div className="stock-team__history">
        <span className="eyebrow">Track record for {ticker}</span>
        <TrackRecord key={historyRefreshKey} ticker={ticker} compact />
      </div>
    </div>
  )
}
