import { useState } from 'react'
import './PriceChart.css'

const PERIODS = [
  { value: '1d', label: '1D' },
  { value: '1mo', label: '1M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
]

/**
 * Single-series price line with a hover crosshair + tooltip (dataviz
 * skill's interaction rule: any line/area chart ships a hover layer, not
 * just a static polyline).
 */
export default function PriceChart({ prices, period, onPeriodChange, positive }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const width = 640
  const height = 220
  const padding = 8

  const hasData = prices && prices.length > 1
  const min = hasData ? Math.min(...prices) : 0
  const max = hasData ? Math.max(...prices) : 1
  const range = max - min || 1
  const stepX = hasData ? (width - padding * 2) / (prices.length - 1) : 0

  const toXY = (v, i) => [
    padding + i * stepX,
    padding + (height - padding * 2) * (1 - (v - min) / range),
  ]

  const points = hasData ? prices.map((v, i) => toXY(v, i)) : []
  const lineColor = positive ? 'var(--good)' : 'var(--critical)'

  function handleMove(e) {
    if (!hasData) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * width
    const index = Math.round((x - padding) / stepX)
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
          <polyline
            points={points.map(([x, y]) => `${x},${y}`).join(' ')}
            fill="none"
            stroke={lineColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {hoverIndex !== null && (
            <>
              <line
                x1={points[hoverIndex][0]}
                x2={points[hoverIndex][0]}
                y1={padding}
                y2={height - padding}
                stroke="var(--border-strong)"
                strokeWidth="1"
              />
              <circle cx={points[hoverIndex][0]} cy={points[hoverIndex][1]} r="4" fill={lineColor} />
            </>
          )}
        </svg>
      )}
      {hoverIndex !== null && hasData && (
        <div className="price-chart__tooltip">${prices[hoverIndex].toFixed(2)}</div>
      )}
    </div>
  )
}
