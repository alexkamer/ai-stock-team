import './RangeBar.css'

export default function RangeBar({ low, high, value, valueLabel = 'Current price', secondaryValue, secondaryLabel }) {
  if (low == null || high == null || value == null || high <= low) return null
  const toPct = (v) => Math.max(0, Math.min(100, ((v - low) / (high - low)) * 100))
  return (
    <div className="range-bar">
      <div className="range-bar__track">
        <div className="range-bar__marker" style={{ left: `${toPct(value)}%` }} title={valueLabel} />
        {secondaryValue != null && (
          <div
            className="range-bar__marker range-bar__marker--secondary"
            style={{ left: `${toPct(secondaryValue)}%` }}
            title={secondaryLabel}
          />
        )}
      </div>
      {secondaryValue != null && (
        <div className="range-bar__legend">
          <span className="range-bar__legend-item">
            <span className="range-bar__legend-swatch range-bar__legend-swatch--primary" /> {valueLabel}
          </span>
          <span className="range-bar__legend-item">
            <span className="range-bar__legend-swatch range-bar__legend-swatch--secondary" /> {secondaryLabel}
          </span>
        </div>
      )}
      <div className="range-bar__labels">
        <span className="num">{low.toFixed(2)}</span>
        <span className="num">{high.toFixed(2)}</span>
      </div>
    </div>
  )
}
