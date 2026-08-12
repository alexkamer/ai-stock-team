import { useState } from 'react'
import './RowCompareChart.css'

function pathFromPoints(pts) {
  return pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ')
}

/**
 * Multi-line chart comparing one numeric field's history across the tickers
 * in a comparison table row (e.g. market value over time). One line per
 * ticker in a fixed categorical color (dataviz skill: identity is the job
 * here, so categorical hue + a legend, never color-alone).
 */
export default function RowCompareChart({ series, formatValue, colorOf, interval, onIntervalChange }) {
  const [hoverIndex, setHoverIndex] = useState(null)

  const width = 640
  const height = 220
  const padTop = 16
  const padBottom = 24
  const padLeft = 8
  const padRight = 64

  const labels = series[0]?.labels ?? []
  const allValues = series.flatMap((s) => s.values.filter((v) => v != null))
  const hasData = labels.length > 1 && allValues.length > 0

  const rawMin = hasData ? Math.min(...allValues) : 0
  const rawMax = hasData ? Math.max(...allValues) : 1
  const rawRange = rawMax - rawMin || 1
  const min = rawMin - rawRange * 0.08
  const max = rawMax + rawRange * 0.08
  const range = max - min || 1

  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom
  const stepX = hasData ? plotWidth / (labels.length - 1) : 0

  const toXY = (v, i) => [padLeft + i * stepX, padTop + plotHeight * (1 - (v - min) / range)]

  const lines = series.map((s) => ({
    ticker: s.ticker,
    points: s.values.map((v, i) => toXY(v, i)),
  }))

  const gridValues = Array.from({ length: 5 }, (_, i) => min + (range * i) / 4)

  const distinctLabelIndices = []
  labels.forEach((text, i) => {
    const prevText = distinctLabelIndices.length ? labels[distinctLabelIndices[distinctLabelIndices.length - 1]] : null
    if (text !== prevText) distinctLabelIndices.push(i)
  })
  // Evenly-spaced stride (every Nth month) rather than distributing a fixed
  // label count across the range - the latter rounds each pick independently,
  // which can land two labels one month apart right next to a two-month gap.
  const labelStride = Math.max(1, Math.round(distinctLabelIndices.length / 7))
  const dateLabelIndices = distinctLabelIndices.filter((_, i) => i % labelStride === 0)

  function updateHoverFromClientX(clientX, svgEl) {
    if (!hasData) return
    const rect = svgEl.getBoundingClientRect()
    const x = ((clientX - rect.left) / rect.width) * width
    const index = Math.round((x - padLeft) / stepX)
    setHoverIndex(Math.max(0, Math.min(labels.length - 1, index)))
  }

  if (!hasData) {
    return <div className="row-compare-chart__loading">Loading chart…</div>
  }

  return (
    <div className="row-compare-chart">
      <div className="row-compare-chart__header">
        <div className="row-compare-chart__legend">
          {series.map((s) => (
            <span key={s.ticker} className="row-compare-chart__legend-item">
              <span className="row-compare-chart__legend-swatch" style={{ background: colorOf(s.ticker) }} />
              {s.ticker}
            </span>
          ))}
        </div>
        {onIntervalChange && (
          <div className="row-compare-chart__interval" role="group" aria-label="Chart interval">
            <button
              type="button"
              className={`row-compare-chart__interval-btn${interval === '1mo' ? ' row-compare-chart__interval-btn--active' : ''}`}
              onClick={() => onIntervalChange('1mo')}
            >
              Monthly
            </button>
            <button
              type="button"
              className={`row-compare-chart__interval-btn${interval === '3mo' ? ' row-compare-chart__interval-btn--active' : ''}`}
              onClick={() => onIntervalChange('3mo')}
            >
              Quarterly
            </button>
          </div>
        )}
      </div>
      <div className="row-compare-chart__plot">
        <svg
          width="100%"
          viewBox={`0 0 ${width} ${height}`}
          onMouseMove={(e) => updateHoverFromClientX(e.clientX, e.currentTarget)}
          onMouseLeave={() => setHoverIndex(null)}
          role="img"
          aria-label="Line chart comparing market value over time across tickers"
        >
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
                  strokeDasharray={i === 0 || i === 4 ? undefined : '3 4'}
                />
                <text x={width - 4} y={y} dy="3" textAnchor="end" className="row-compare-chart__axis-label">
                  {formatValue(v)}
                </text>
              </g>
            )
          })}

          {dateLabelIndices.map((idx, i) => {
            const isFirst = i === 0
            const isLast = i === dateLabelIndices.length - 1
            const anchor = isFirst ? 'start' : isLast ? 'end' : 'middle'
            return (
              <text
                key={idx}
                x={lines[0].points[idx][0]}
                y={height - padBottom + 16}
                textAnchor={anchor}
                className="row-compare-chart__axis-label"
              >
                {labels[idx]}
              </text>
            )
          })}

          {lines.map((line) => (
            <path
              key={line.ticker}
              d={pathFromPoints(line.points)}
              fill="none"
              stroke={colorOf(line.ticker)}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {hoverIndex !== null && (
            <>
              <line
                x1={lines[0].points[hoverIndex][0]}
                x2={lines[0].points[hoverIndex][0]}
                y1={padTop}
                y2={padTop + plotHeight}
                stroke="var(--border-strong)"
                strokeWidth="1"
              />
              {lines.map((line) => (
                <circle
                  key={line.ticker}
                  cx={line.points[hoverIndex][0]}
                  cy={line.points[hoverIndex][1]}
                  r="4"
                  fill={colorOf(line.ticker)}
                  stroke="var(--surface-1)"
                  strokeWidth="2"
                />
              ))}
            </>
          )}
        </svg>
        {hoverIndex !== null && (
          <div
            className="row-compare-chart__tooltip"
            style={{
              left: `${Math.min(88, Math.max(4, (lines[0].points[hoverIndex][0] / width) * 100))}%`,
            }}
          >
            <span className="row-compare-chart__tooltip-date">{labels[hoverIndex]}</span>
            {series.map((s) => (
              <div className="row-compare-chart__tooltip-row" key={s.ticker}>
                <span className="row-compare-chart__tooltip-swatch" style={{ background: colorOf(s.ticker) }} />
                <span className="num">{s.ticker}</span>
                <span className="num row-compare-chart__tooltip-value">
                  {s.values[hoverIndex] != null ? formatValue(s.values[hoverIndex]) : '—'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
