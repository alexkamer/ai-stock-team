import { useId, useState } from 'react'
import './ThemePerformanceChart.css'

const GRID_ROWS = 4
const BASELINE = 100

function pathFromPoints(pts) {
  return pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ')
}

// Daily points are date-only ("2026-09-01"); the same-day intraday
// fallback (see agents/theme_builder.py's _intraday_version_return_index)
// produces full timestamps instead - those read better as a time than a
// date since they're all from today.
function formatDate(iso) {
  if (iso.includes('T')) {
    return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  }
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatAxisPercent(v) {
  const pct = v - BASELINE
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`
}

/**
 * Single-series index chart of a theme's P/L since it was first bought,
 * chain-linked across every "Update theme" version (see
 * agents/theme_builder.py's get_theme_performance) - a dashed marker at
 * each update date, gridlines, a dashed 100 (buy-in) reference line, and
 * a hover crosshair + tooltip (dataviz skill's interaction rule for any
 * line chart). One series, so no legend box - the heading names it.
 */
export default function ThemePerformanceChart({ points, updates, loading }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const gradientId = useId()
  const width = 640
  const height = 200
  const padTop = 12
  const padBottom = 26
  const padLeft = 8
  const padRight = 52

  const hasData = points && points.length > 1
  const values = hasData ? points.map((p) => p.value) : [BASELINE]

  const rawMin = Math.min(...values, BASELINE)
  const rawMax = Math.max(...values, BASELINE)
  const rawRange = rawMax - rawMin || 1
  const min = rawMin - rawRange * 0.1
  const max = rawMax + rawRange * 0.1
  const range = max - min || 1
  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom
  const stepX = hasData ? plotWidth / (points.length - 1) : 0

  const toXY = (v, i) => [padLeft + i * stepX, padTop + plotHeight * (1 - (v - min) / range)]
  const coords = hasData ? points.map((p, i) => toXY(p.value, i)) : []
  const baselineY = padTop + plotHeight * (1 - (BASELINE - min) / range)

  const finalValue = hasData ? points[points.length - 1].value : BASELINE
  const lineColor = finalValue >= BASELINE ? 'var(--good)' : 'var(--critical)'
  const totalChangePercent = finalValue - BASELINE

  const linePath = hasData ? pathFromPoints(coords) : ''
  const areaPath = hasData
    ? `M${coords[0][0]},${baselineY} ` + coords.map(([x, y]) => `L${x},${y}`).join(' ') + ` L${coords[coords.length - 1][0]},${baselineY} Z`
    : ''

  const gridValues = Array.from({ length: GRID_ROWS + 1 }, (_, i) => min + (range * i) / GRID_ROWS)

  const dateLabelCount = hasData ? Math.min(5, points.length) : 0
  const dateLabelIndices =
    dateLabelCount > 1
      ? Array.from({ length: dateLabelCount }, (_, i) => Math.round((i * (points.length - 1)) / (dateLabelCount - 1)))
      : []

  // Skip index 0 - the first "update" is the theme's original buy-in, not
  // a change worth marking on the line.
  const updateMarkers = hasData
    ? (updates ?? [])
        .slice(1)
        .map((u) => {
          const idx = points.findIndex((p) => p.date === u.date)
          return idx === -1 ? null : { ...u, x: coords[idx][0] }
        })
        .filter(Boolean)
    : []

  function updateHoverFromClientX(clientX, svgEl) {
    if (!hasData) return
    const rect = svgEl.getBoundingClientRect()
    const x = ((clientX - rect.left) / rect.width) * width
    const index = Math.round((x - padLeft) / stepX)
    setHoverIndex(Math.max(0, Math.min(points.length - 1, index)))
  }

  const tooltipLeftPct = hoverIndex !== null ? Math.min(92, Math.max(8, (coords[hoverIndex][0] / width) * 100)) : null
  const tooltipTopPct = hoverIndex !== null ? (coords[hoverIndex][1] / height) * 100 : null

  return (
    <div className="theme-perf-chart">
      <div className="theme-perf-chart__header">
        <h4>Performance since buy-in</h4>
        {hasData && (
          <span className={`theme-perf-chart__total num theme-perf-chart__total--${totalChangePercent >= 0 ? 'up' : 'down'}`}>
            {totalChangePercent >= 0 ? '+' : ''}
            {totalChangePercent.toFixed(2)}%
          </span>
        )}
      </div>
      {!hasData ? (
        <p className="theme-perf-chart__empty">
          {loading ? 'Loading…' : "No price data yet - check back once the market's open."}
        </p>
      ) : (
        <div className="theme-perf-chart__plot">
          <svg
            width="100%"
            viewBox={`0 0 ${width} ${height}`}
            onMouseMove={(e) => updateHoverFromClientX(e.clientX, e.currentTarget)}
            onMouseLeave={() => setHoverIndex(null)}
            onTouchStart={(e) => updateHoverFromClientX(e.touches[0].clientX, e.currentTarget)}
            onTouchMove={(e) => {
              e.preventDefault()
              updateHoverFromClientX(e.touches[0].clientX, e.currentTarget)
            }}
            onTouchEnd={() => setHoverIndex(null)}
            role="img"
            aria-label="Theme performance since buy-in"
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity="0.2" />
                <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
              </linearGradient>
            </defs>

            {gridValues.map((v, i) => {
              const y = padTop + plotHeight * (1 - (v - min) / range)
              return (
                <g key={i}>
                  <line x1={padLeft} x2={width - padRight} y1={y} y2={y} stroke="var(--border)" strokeWidth="1" strokeDasharray="3 4" />
                  <text x={width - padRight + 8} y={y} dy="3" className="theme-perf-chart__axis-label">
                    {formatAxisPercent(v)}
                  </text>
                </g>
              )
            })}

            <line x1={padLeft} x2={width - padRight} y1={baselineY} y2={baselineY} stroke="var(--text-muted)" strokeWidth="1" strokeDasharray="4 3" />
            <text x={padLeft + 4} y={baselineY} dy={-4} className="theme-perf-chart__axis-label">
              0.00% (buy-in)
            </text>

            {dateLabelIndices.map((idx, i) => (
              <text
                key={idx}
                x={coords[idx][0]}
                y={height - padBottom + 18}
                textAnchor={i === 0 ? 'start' : i === dateLabelIndices.length - 1 ? 'end' : 'middle'}
                className="theme-perf-chart__axis-label"
              >
                {formatDate(points[idx].date)}
              </text>
            ))}

            {updateMarkers.map((u) => (
              <line
                key={u.date}
                x1={u.x}
                x2={u.x}
                y1={padTop}
                y2={padTop + plotHeight}
                stroke="var(--signal)"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
            ))}

            <path d={areaPath} fill={`url(#${gradientId})`} />
            <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

            {hoverIndex !== null && (
              <>
                <line
                  x1={coords[hoverIndex][0]}
                  x2={coords[hoverIndex][0]}
                  y1={padTop}
                  y2={padTop + plotHeight}
                  stroke="var(--border-strong)"
                  strokeWidth="1"
                />
                <circle cx={coords[hoverIndex][0]} cy={coords[hoverIndex][1]} r="4" fill={lineColor} />
              </>
            )}
          </svg>
          {hoverIndex !== null && (
            <div className="theme-perf-chart__tooltip" style={{ left: `${tooltipLeftPct}%`, top: `${tooltipTopPct}%` }}>
              <span className="num theme-perf-chart__tooltip-value">
                {points[hoverIndex].value >= BASELINE ? '+' : ''}
                {(points[hoverIndex].value - BASELINE).toFixed(2)}%
              </span>
              <span className="theme-perf-chart__tooltip-date">{formatDate(points[hoverIndex].date)}</span>
            </div>
          )}
        </div>
      )}
      {updateMarkers.length > 0 && (
        <p className="theme-perf-chart__legend">
          <span className="theme-perf-chart__legend-swatch" /> Update theme
        </p>
      )}
    </div>
  )
}
