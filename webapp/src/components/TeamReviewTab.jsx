import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON, streamSSE } from '../api/client'
import { teamReviewCache } from '../api/teamReviewCache'
import './TeamReviewTab.css'

const VERDICT_LABEL = { buy: 'Buy', hold: 'Hold', sell: 'Sell' }

// Positions at or above this weight are pre-selected for a batch run -
// smaller ones rarely move the needle on the portfolio, so they default to
// unchecked (but stay selectable) rather than spending money analyzing them
// every time. Real measured cost per full team analysis is ~$0.14 (Claude
// Sonnet 5 via Bedrock, 6 specialists + synthesizer) - see conversation.
const MATERIAL_WEIGHT_PERCENT = 2
const COST_PER_ANALYSIS_USD = 0.14

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function VerdictBadge({ verdict }) {
  if (!verdict) return null
  return <span className={`team-review__verdict-badge team-review__verdict-badge--${verdict}`}>{VERDICT_LABEL[verdict]}</span>
}

export default function TeamReviewTab({ positions, totalValue }) {
  const [latestByTicker, setLatestByTicker] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [skipAnalyzedToday, setSkipAnalyzedToday] = useState(true)
  // Seeded from the module-scoped cache (not component state) so a batch run
  // kicked off earlier - possibly while this component was unmounted - still
  // shows its in-progress/completed status on remount.
  const [statusByTicker, setStatusByTicker] = useState(() => teamReviewCache.statusByTicker)

  const setStatus = useCallback((updater) => {
    setStatusByTicker((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      teamReviewCache.statusByTicker = next
      return next
    })
  }, [])

  const rows = (positions ?? [])
    .filter((p) => p.symbol && p.value != null)
    .map((p) => ({ symbol: p.symbol, description: p.description, value: p.value, weight: totalValue ? (p.value / totalValue) * 100 : 0 }))
    .sort((a, b) => b.weight - a.weight)

  useEffect(() => {
    if (rows.length === 0) return
    const symbols = rows.map((r) => r.symbol)
    getJSON(`/track-record?tickers=${symbols.join(',')}`).then((data) => {
      const latest = {}
      for (const record of data.records) {
        if (!latest[record.ticker] || record.call_date > latest[record.ticker].call_date) {
          latest[record.ticker] = record
        }
      }
      setLatestByTicker(latest)
      setSelected(new Set(rows.filter((r) => r.weight >= MATERIAL_WEIGHT_PERCENT).map((r) => r.symbol)))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions, totalValue])

  if (rows.length === 0) {
    return <p className="team-review__empty">No holdings to analyze.</p>
  }

  const isAnalyzedToday = (symbol) => latestByTicker?.[symbol]?.call_date === todayIso()

  const eligibleSymbols = rows
    .map((r) => r.symbol)
    .filter((symbol) => selected.has(symbol) && (!skipAnalyzedToday || !isAnalyzedToday(symbol)))

  const toggle = (symbol) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

  const runAnalysis = () => {
    for (const symbol of eligibleSymbols) {
      setStatus((prev) => ({ ...prev, [symbol]: { state: 'running' } }))

      // No AbortController/signal here deliberately - this is a background
      // batch job. Unmounting this component (switching tabs, navigating
      // away) must not cancel the underlying request, since the whole point
      // is that it keeps running and logging server-side either way.
      streamSSE(`/tickers/${symbol}/team`, {
        onEvent: (eventName, data) => {
          if (eventName === 'verdict') {
            setStatus((prev) => ({ ...prev, [symbol]: { state: 'done', verdict: data } }))
            setLatestByTicker((prev) => ({
              ...prev,
              [symbol]: { ticker: symbol, verdict: data.verdict, call_date: todayIso() },
            }))
          } else if (eventName === 'error') {
            setStatus((prev) => ({ ...prev, [symbol]: { state: 'error', message: data.detail } }))
          }
        },
      }).catch((e) => {
        setStatus((prev) => ({ ...prev, [symbol]: { state: 'error', message: e.message } }))
      })
    }
  }

  const running = Object.values(statusByTicker).some((s) => s.state === 'running')
  const estimatedCost = (eligibleSymbols.length * COST_PER_ANALYSIS_USD).toFixed(2)

  return (
    <div className="team-review">
      <div className="team-review__controls">
        <label className="team-review__skip-toggle">
          <input type="checkbox" checked={skipAnalyzedToday} onChange={(e) => setSkipAnalyzedToday(e.target.checked)} />
          Skip holdings already analyzed today
        </label>
        <button type="button" className="team-review__run-button" onClick={runAnalysis} disabled={running || eligibleSymbols.length === 0}>
          {running
            ? 'Analyzing…'
            : eligibleSymbols.length === 0
              ? 'Nothing to analyze'
              : `Analyze ${eligibleSymbols.length} holding${eligibleSymbols.length === 1 ? '' : 's'} (~$${estimatedCost})`}
        </button>
      </div>

      <div className="card team-review__table-card">
        <table className="team-review__table">
          <thead>
            <tr>
              <th></th>
              <th>Ticker</th>
              <th>Weight</th>
              <th>Last verdict</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const latest = latestByTicker?.[row.symbol]
              const status = statusByTicker[row.symbol]
              return (
                <tr key={row.symbol}>
                  <td>
                    <input type="checkbox" checked={selected.has(row.symbol)} onChange={() => toggle(row.symbol)} />
                  </td>
                  <td>
                    <Link to={`/tickers/${row.symbol}/team`}>{row.symbol}</Link>
                  </td>
                  <td className="num">{row.weight.toFixed(1)}%</td>
                  <td>
                    {latest ? (
                      <>
                        <VerdictBadge verdict={latest.verdict} />{' '}
                        <span className="team-review__cell--muted">{latest.call_date}</span>
                      </>
                    ) : (
                      <span className="team-review__cell--muted">Never analyzed</span>
                    )}
                  </td>
                  <td>
                    {status?.state === 'running' ? (
                      <span className="team-review__cell--muted">Analyzing…</span>
                    ) : status?.state === 'done' ? (
                      <VerdictBadge verdict={status.verdict.verdict} />
                    ) : status?.state === 'error' ? (
                      <span className="team-review__cell--error">{status.message}</span>
                    ) : isAnalyzedToday(row.symbol) ? (
                      <span className="team-review__cell--muted">Up to date</span>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
