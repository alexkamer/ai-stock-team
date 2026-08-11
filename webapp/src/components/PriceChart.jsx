import { useId, useState } from 'react'
import './PriceChart.css'

const PERIODS = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1mo', label: '1M' },
  { value: '6mo', label: '6M' },
  { value: 'ytd', label: 'YTD' },
  { value: '1y', label: '1Y' },
  { value: '5y', label: '5Y' },
  { value: 'max', label: 'MAX' },
]

const GRID_ROWS = 4

function normalize(series) {
  const base = series[0]
  return series.map((v) => ((v - base) / base) * 100)
}

function formatVolume(v) {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return `${v}`
}

// Splits a line into runs colored by whether the underlying value is above
// or below a reference (previous close), interpolating the exact crossing
// point so the color switches right where the line meets the reference.
function buildColoredSegments(points, values, threshold, goodColor, criticalColor) {
  if (!points.length) return []
  const colorOf = (v) => (v >= threshold ? goodColor : criticalColor)
  const segments = []
  let currentColor = colorOf(values[0])
  let currentPoints = [points[0]]
  for (let i = 1; i < points.length; i++) {
    const prevVal = values[i - 1]
    const curVal = values[i]
    const curColor = colorOf(curVal)
    if (curColor === currentColor) {
      currentPoints.push(points[i])
      continue
    }
    const t = (threshold - prevVal) / (curVal - prevVal)
    const crossX = points[i - 1][0] + t * (points[i][0] - points[i - 1][0])
    const crossY = points[i - 1][1] + t * (points[i][1] - points[i - 1][1])
    currentPoints.push([crossX, crossY])
    segments.push({ points: currentPoints, color: currentColor })
    currentPoints = [[crossX, crossY], points[i]]
    currentColor = curColor
  }
  segments.push({ points: currentPoints, color: currentColor })
  return segments
}

function pathFromPoints(pts) {
  return pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ')
}

/**
 * Single-series price line with gridlines, a price axis, a handful of date
 * labels, a gradient area fill, a volume strip, an optional previous-close
 * reference line, an optional normalized benchmark overlay, and a hover
 * crosshair + floating tooltip (dataviz skill's interaction rule: any
 * line/area chart ships a hover layer, not just a static polyline).
 */
export default function PriceChart({
  ticker,
  prices,
  labels,
  volumes,
  opens,
  highs,
  lows,
  period,
  onPeriodChange,
  positive,
  previousClose,
  loading,
  benchmarkPrices,
  benchmarkLabel,
  compareEnabled,
  onToggleCompare,
  chartType,
  onChartTypeChange,
}) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const gradientId = useId()
  const goodGradientId = useId()
  const criticalGradientId = useId()
  const width = 640
  const height = 240
  const padTop = 12
  const padBottom = 28
  const padLeft = 8
  const padRight = 52

  const hasData = prices && prices.length > 1
  const isStale = loading && hasData
  const hasVolume = hasData && Array.isArray(volumes) && volumes.length === prices.length
  const hasOhl =
    hasData &&
    Array.isArray(opens) &&
    Array.isArray(highs) &&
    Array.isArray(lows) &&
    opens.length === prices.length &&
    highs.length === prices.length &&
    lows.length === prices.length
  const isIntraday = period === '1d' || period === '5d'
  const compareMode =
    hasData && compareEnabled && Array.isArray(benchmarkPrices) && benchmarkPrices.length === prices.length
  const candleMode = chartType === 'candle' && hasOhl && !compareMode

  const primaryPct = compareMode ? normalize(prices) : null
  const benchmarkPct = compareMode ? normalize(benchmarkPrices) : null
  const plotSeries = compareMode ? primaryPct : prices

  const volumeHeight = hasVolume ? 44 : 0
  const volumeGap = hasVolume ? 6 : 0
  const plotWidth = width - padLeft - padRight
  const pricePlotHeight = height - padTop - padBottom - volumeHeight - volumeGap
  const volumeTop = padTop + pricePlotHeight + volumeGap
  const volumeBottom = volumeTop + volumeHeight

  const scaleValues = hasData
    ? compareMode
      ? [...primaryPct, ...benchmarkPct]
      : candleMode
        ? [...highs, ...lows]
        : plotSeries
    : [0]
  const rawMin = hasData ? Math.min(...scaleValues) : 0
  const rawMax = hasData ? Math.max(...scaleValues) : 1
  const rawRange = rawMax - rawMin || 1
  const AXIS_PADDING_RATIO = 0.08
  const min = rawMin - rawRange * AXIS_PADDING_RATIO
  const max = rawMax + rawRange * AXIS_PADDING_RATIO
  const range = max - min || 1
  const stepX = hasData ? plotWidth / (prices.length - 1) : 0

  const toXY = (v, i) => [
    padLeft + i * stepX,
    padTop + pricePlotHeight * (1 - (v - min) / range),
  ]

  const points = hasData ? plotSeries.map((v, i) => toXY(v, i)) : []
  const benchmarkPoints = compareMode ? benchmarkPct.map((v, i) => toXY(v, i)) : []
  const lineColor = positive ? 'var(--good)' : 'var(--critical)'

  const relativeToPrevClose = hasData && !compareMode && isIntraday && previousClose != null
  const coloredSegments = relativeToPrevClose
    ? buildColoredSegments(points, prices, previousClose, 'var(--good)', 'var(--critical)')
    : null

  const baseline = padTop + pricePlotHeight
  let prevCloseY = null
  let prevCloseInRange = true
  if (relativeToPrevClose) {
    prevCloseY = padTop + pricePlotHeight * (1 - (previousClose - min) / range)
    prevCloseInRange = previousClose >= min && previousClose <= max
    prevCloseY = Math.max(padTop, Math.min(baseline, prevCloseY))
  }

  const areaPathFor = (pts, base = baseline) =>
    `M${pts[0][0]},${base} ` + pts.map(([x, y]) => `L${x},${y}`).join(' ') + ` L${pts[pts.length - 1][0]},${base} Z`
  const areaPath = hasData ? areaPathFor(points) : ''
  const linePath = hasData ? pathFromPoints(points) : ''
  const benchmarkPath = compareMode ? pathFromPoints(benchmarkPoints) : ''

  const gridValues = Array.from({ length: GRID_ROWS + 1 }, (_, i) => min + (range * i) / GRID_ROWS)

  // Pick date labels from distinct label text so dense intraday data
  // doesn't repeat the same timestamp under multiple gridlines.
  const distinctLabelIndices = []
  if (hasData && labels) {
    labels.forEach((text, i) => {
      const prevText = distinctLabelIndices.length ? labels[distinctLabelIndices[distinctLabelIndices.length - 1]] : null
      if (text !== prevText) distinctLabelIndices.push(i)
    })
  }
  const dateLabelCount = Math.min(5, distinctLabelIndices.length)
  const dateLabelIndices =
    dateLabelCount > 1
      ? Array.from(
          { length: dateLabelCount },
          (_, i) => distinctLabelIndices[Math.round((i * (distinctLabelIndices.length - 1)) / (dateLabelCount - 1))]
        )
      : distinctLabelIndices

  const volMax = hasVolume ? Math.max(...volumes, 1) : 1
  const barWidth = hasVolume ? Math.max(0.5, stepX * 0.6) : 0
  const volBarY = (v) => volumeBottom - (v / volMax) * volumeHeight
  const volBarH = (v) => (v / volMax) * volumeHeight

  const candleWidth = candleMode ? Math.max(1, stepX * 0.6) : 0
  const priceToY = (v) => padTop + pricePlotHeight * (1 - (v - min) / range)
  const candles = candleMode
    ? prices.map((close, i) => {
        const up = close >= opens[i]
        return {
          x: points[i][0],
          up,
          wickTop: priceToY(highs[i]),
          wickBottom: priceToY(lows[i]),
          bodyTop: priceToY(Math.max(opens[i], close)),
          bodyBottom: priceToY(Math.min(opens[i], close)),
        }
      })
    : []

  const showPrevClose = relativeToPrevClose

  function updateHoverFromClientX(clientX, svgEl) {
    if (!hasData) return
    const rect = svgEl.getBoundingClientRect()
    const x = ((clientX - rect.left) / rect.width) * width
    const index = Math.round((x - padLeft) / stepX)
    setHoverIndex(Math.max(0, Math.min(prices.length - 1, index)))
  }

  function formatAxisValue(v) {
    if (compareMode) return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
    return `$${v.toFixed(v < 10 ? 2 : 0)}`
  }

  const tooltipLeftPct = hoverIndex !== null ? Math.min(92, Math.max(8, (points[hoverIndex][0] / width) * 100)) : null
  const tooltipTopPct = hoverIndex !== null ? (points[hoverIndex][1] / height) * 100 : null

  return (
    <div className="price-chart">
      <div className="price-chart__header">
        <div className="price-chart__meta">
          <button
            className={`price-chart__compare-toggle${compareEnabled ? ' price-chart__compare-toggle--active' : ''}`}
            onClick={onToggleCompare}
          >
            <span className="price-chart__compare-dot" style={compareEnabled ? { background: lineColor } : undefined} />
            {ticker ?? 'Stock'}
            {compareMode && (
              <span className="price-chart__compare-vs">
                <span className="price-chart__compare-dash" /> {benchmarkLabel}
              </span>
            )}
            {!compareEnabled && <span className="price-chart__compare-hint">vs {benchmarkLabel}</span>}
          </button>
          {hasOhl && !compareEnabled && (
            <div className="price-chart__type-toggle" role="group" aria-label="Chart type">
              <button
                className={`price-chart__type-btn${chartType === 'line' ? ' price-chart__type-btn--active' : ''}`}
                onClick={() => onChartTypeChange('line')}
              >
                Line
              </button>
              <button
                className={`price-chart__type-btn${chartType === 'candle' ? ' price-chart__type-btn--active' : ''}`}
                onClick={() => onChartTypeChange('candle')}
              >
                Candle
              </button>
            </div>
          )}
        </div>
        <div className="price-chart__periods" role="group" aria-label="Time range">
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
      </div>
      {!hasData ? (
        <div className="price-chart__loading">Loading chart…</div>
      ) : (
        <div className={`price-chart__plot${isStale ? ' price-chart__plot--stale' : ''}`}>
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
            onTouchCancel={() => setHoverIndex(null)}
            role="img"
            aria-label="Price history"
          >
            <defs>
              {relativeToPrevClose ? (
                <>
                  <linearGradient id={goodGradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--good)" stopOpacity="0.22" />
                    <stop offset="100%" stopColor="var(--good)" stopOpacity="0" />
                  </linearGradient>
                  <linearGradient id={criticalGradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--critical)" stopOpacity="0.22" />
                    <stop offset="100%" stopColor="var(--critical)" stopOpacity="0" />
                  </linearGradient>
                </>
              ) : (
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={lineColor} stopOpacity="0.22" />
                  <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
                </linearGradient>
              )}
            </defs>

            {gridValues.map((v, i) => {
              const y = padTop + pricePlotHeight * (1 - (v - min) / range)
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
                    {formatAxisValue(v)}
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
                  x={points[idx][0]}
                  y={height - padBottom + 18}
                  textAnchor={anchor}
                  className="price-chart__axis-label"
                >
                  {labels[idx]}
                </text>
              )
            })}

            {showPrevClose && (
              <g>
                <line
                  x1={padLeft}
                  x2={width - padRight}
                  y1={prevCloseY}
                  y2={prevCloseY}
                  stroke="var(--text-muted)"
                  strokeWidth="1"
                  strokeDasharray="4 3"
                />
                <text
                  x={padLeft + 4}
                  y={prevCloseY}
                  dy={prevCloseInRange ? -4 : prevCloseY === padTop ? 10 : -4}
                  className="price-chart__axis-label"
                >
                  Prev close ${previousClose.toFixed(2)}
                </text>
              </g>
            )}

            {candleMode ? (
              candles.map((c, i) => (
                <g key={i}>
                  <line
                    x1={c.x}
                    x2={c.x}
                    y1={c.wickTop}
                    y2={c.wickBottom}
                    stroke={c.up ? 'var(--good)' : 'var(--critical)'}
                    strokeWidth="1"
                  />
                  <rect
                    x={c.x - candleWidth / 2}
                    y={c.bodyTop}
                    width={candleWidth}
                    height={Math.max(1, c.bodyBottom - c.bodyTop)}
                    fill={c.up ? 'var(--good)' : 'var(--critical)'}
                  />
                </g>
              ))
            ) : (
              <>
                {relativeToPrevClose ? (
                  coloredSegments.map((seg, i) => (
                    <path
                      key={i}
                      d={areaPathFor(seg.points, prevCloseY)}
                      fill={`url(#${seg.color === 'var(--good)' ? goodGradientId : criticalGradientId})`}
                    />
                  ))
                ) : (
                  <path d={areaPath} fill={`url(#${gradientId})`} />
                )}
                {compareMode && (
                  <path
                    d={benchmarkPath}
                    fill="none"
                    stroke="var(--text-secondary)"
                    strokeWidth="1.5"
                    strokeDasharray="5 3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                )}
                {relativeToPrevClose ? (
                  coloredSegments.map((seg, i) => (
                    <path
                      key={i}
                      d={pathFromPoints(seg.points)}
                      fill="none"
                      stroke={seg.color}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  ))
                ) : (
                  <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                )}
              </>
            )}

            {hasVolume &&
              volumes.map((v, i) => {
                const up = i === 0 ? true : prices[i] >= prices[i - 1]
                return (
                  <rect
                    key={i}
                    x={points[i][0] - barWidth / 2}
                    y={volBarY(v)}
                    width={barWidth}
                    height={volBarH(v)}
                    fill={up ? 'var(--good)' : 'var(--critical)'}
                    opacity="0.55"
                  />
                )
              })}

            {hoverIndex !== null && (
              <>
                <line
                  x1={points[hoverIndex][0]}
                  x2={points[hoverIndex][0]}
                  y1={padTop}
                  y2={padTop + pricePlotHeight}
                  stroke="var(--border-strong)"
                  strokeWidth="1"
                />
                {!candleMode && (
                  <circle
                    cx={points[hoverIndex][0]}
                    cy={points[hoverIndex][1]}
                    r="4"
                    fill={relativeToPrevClose ? (prices[hoverIndex] >= previousClose ? 'var(--good)' : 'var(--critical)') : lineColor}
                  />
                )}
                {compareMode && (
                  <circle
                    cx={benchmarkPoints[hoverIndex][0]}
                    cy={benchmarkPoints[hoverIndex][1]}
                    r="4"
                    fill="none"
                    stroke="var(--text-secondary)"
                    strokeWidth="1.5"
                  />
                )}
              </>
            )}
          </svg>
          {isStale && (
            <div className="price-chart__spinner-overlay">
              <span className="spinner" />
            </div>
          )}
          {hoverIndex !== null && (
            <div
              className="price-chart__tooltip"
              style={{ left: `${tooltipLeftPct}%`, top: `${tooltipTopPct}%` }}
            >
              {compareMode ? (
                <>
                  <div className="price-chart__tooltip-row">
                    <span className="price-chart__tooltip-swatch" style={{ background: lineColor }} />
                    <span className="num">
                      {ticker ?? 'Stock'} {primaryPct[hoverIndex] >= 0 ? '+' : ''}
                      {primaryPct[hoverIndex].toFixed(2)}%
                    </span>
                  </div>
                  <div className="price-chart__tooltip-row">
                    <span className="price-chart__tooltip-swatch price-chart__tooltip-swatch--dashed" />
                    <span className="num price-chart__tooltip-secondary">
                      {benchmarkLabel} {benchmarkPct[hoverIndex] >= 0 ? '+' : ''}
                      {benchmarkPct[hoverIndex].toFixed(2)}%
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <span className="num price-chart__tooltip-price">${prices[hoverIndex].toFixed(2)}</span>
                  {hasOhl && (
                    <div className="price-chart__tooltip-ohlc">
                      <span>
                        O <span className="num">${opens[hoverIndex].toFixed(2)}</span>
                      </span>
                      <span>
                        H <span className="num">${highs[hoverIndex].toFixed(2)}</span>
                      </span>
                      <span>
                        L <span className="num">${lows[hoverIndex].toFixed(2)}</span>
                      </span>
                    </div>
                  )}
                  {hasVolume && (
                    <span className="price-chart__tooltip-volume num">Vol {formatVolume(volumes[hoverIndex])}</span>
                  )}
                </>
              )}
              {labels?.[hoverIndex] && <span className="price-chart__tooltip-date">{labels[hoverIndex]}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
