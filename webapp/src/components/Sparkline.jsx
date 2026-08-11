/**
 * Minimal single-series line chart for a watchlist card. One hue (the
 * sequential/categorical slot-1 blue), no axes/legend/gridlines - a
 * sparkline is read as a shape ("up" vs "down"), not a chart with scales
 * to inspect, so chrome would only add noise here.
 */
export default function Sparkline({ values, width = 100, height = 32, positive }) {
  if (!values || values.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const stepX = width / (values.length - 1)

  const points = values.map((v, i) => {
    const x = i * stepX
    const y = height - ((v - min) / range) * height
    return [x, y]
  })

  const lineStr = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const areaStr = `0,${height} ${lineStr} ${width.toFixed(1)},${height}`
  const color = positive ? 'var(--good)' : 'var(--critical)'
  const openY = height - ((values[0] - min) / range) * height

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Price trend">
      <polygon points={areaStr} fill={color} opacity="0.08" />
      <line
        x1="0"
        y1={openY.toFixed(1)}
        x2={width}
        y2={openY.toFixed(1)}
        stroke="var(--text-secondary)"
        strokeWidth="1"
        strokeDasharray="2 2"
        opacity="0.5"
      />
      <polyline
        points={lineStr}
        fill="none"
        stroke={color}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
