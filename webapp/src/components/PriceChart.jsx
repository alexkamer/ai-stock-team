import { useId, useState } from 'react'
import './PriceChart.css'

const PERIODS = [
  { value: '1d', label: '1D' },
  { value: '1mo', label: '1M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
]

const GRID_ROWS = 4

/**
 * Single-series price line with gridlines, a price axis, a handful of date
 * labels, a gradient area fill, and a hover crosshair + tooltip (dataviz
 * skill's interaction rule: any line/area chart ships a hover layer, not
 * just a static polyline).
 */
export default function PriceChart({ prices, labels, period, onPeriodChange, positive }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const gradientId = useId()
  const width = 640
  const height = 240
  const padTop = 12
  const padBottom = 28
  const padLeft = 8
  const padRight = 52

  const hasData = prices && prices.length > 1
  const min = hasData ? Math.min(...prices) : 0
  const max = hasData ? Math.max(...prices) : 1
  const range = max - min || 1
  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom
  const stepX = hasData ? plotWidth / (prices.length - 1) : 0

  const toXY = (v, i) => [
    padLeft + i * stepX,
    padTop + plotHeight * (1 - (v - min) / range),
  ]

  const points = hasData ? prices.map((v, i) => toXY(v, i)) : []
  const lineColor = positive ? 'var(--good)' : 'var(--critical)'

  const areaPath = hasData
    ? `M${points[0][0]},${padTop + plotHeight} ` +
      points.map(([x, y]) => `L${x},${y}`).join(' ') +
      ` L${points[points.length - 1][0]},${padTop + plotHeight} Z`
    : ''
  const linePath = hasData ? points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ') : ''

  const gridValues = Array.from({ length: GRID_ROWS + 1 }, (_, i) => min + (range * i) / GRID_ROWS)

  const dateLabelCount = Math.min(5, hasData ? labels?.length ?? 0 : 0)
  const dateLabelIndices =
    dateLabelCount > 1
      ? Array.from({ length: dateLabelCount }, (_, i) => Math.round((i * (prices.length - 1)) / (dateLabelCount - 1)))
      : []

  function handleMove(e) {
    if (!hasData) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * width
    const index = Math.round((x - padLeft) / stepX)
    setHoverIndex(Math.max(0, Math.min(prices.length - 1, index)))
  }

  return (
    <div className="price-chart">
      <div className="price-chart__periods">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            className={`price-chart__period-btn${p.value === period ? ' price-chart__period-btn--active' : ''}`}
            onClick={() => onPeriodChange(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>
      {!hasData ? (
        <div className="price-chart__loading">Loading chart…</div>
      ) : (
        <svg
          width="100%"
          viewBox={`0 0 ${width} ${height}`}
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
          role="img"
          aria-label="Price history"
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity="0.22" />
              <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
            </linearGradient>
          </defs>

          {gridValues.map((v, i) => {
            const y = padTop + plotHeight * (1 - (v - min) / range)
            return (
              <g key={i}>
                <line
                  x1={padLeft}
                  x2={width - padRight}
                  y1={y}
                  y2={y}
                  stroke="var(--border)"
                  strokeWidth="1"
                  strokeDasharray={i === 0 || i === GRID_ROWS ? undefined : '3 4'}
                />
                <text x={width - padRight + 8} y={y} dy="3" className="price-chart__axis-label">
                  ${v.toFixed(v < 10 ? 2 : 0)}
                </text>
              </g>
            )
          })}

          {dateLabelIndices.map((idx) => (
            <text
              key={idx}
              x={points[idx][0]}
              y={height - padBottom + 18}
              className="price-chart__axis-label price-chart__axis-label--x"
            >
              {labels[idx]}
            </text>
          ))}

          <path d={areaPath} fill={`url(#${gradientId})`} />
          <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

          {hoverIndex !== null && (
            <>
              <line
                x1={points[hoverIndex][0]}
                x2={points[hoverIndex][0]}
                y1={padTop}
                y2={padTop + plotHeight}
                stroke="var(--border-strong)"
                strokeWidth="1"
              />
              <circle cx={points[hoverIndex][0]} cy={points[hoverIndex][1]} r="4" fill={lineColor} />
            </>
          )}
        </svg>
      )}
      {hoverIndex !== null && hasData && (
        <div className="price-chart__tooltip">
          <span className="num">${prices[hoverIndex].toFixed(2)}</span>
          {labels?.[hoverIndex] && <span className="price-chart__tooltip-date">{labels[hoverIndex]}</span>}
        </div>
      )}
    </div>
  )
}
