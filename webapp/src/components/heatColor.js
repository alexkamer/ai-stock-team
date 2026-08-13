// Diverging color for a tile: --critical at the negative pole, a neutral
// gray midpoint at ~0% change, --good at the positive pole - reads current
// theme values from the DOM so light/dark mode (index.css) stay in sync
// automatically instead of duplicating hex values here.
function readColor(varName, fallback) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  return value || fallback
}

function hexToRgb(hex) {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (!match) return [139, 143, 153]
  return match.slice(1).map((part) => parseInt(part, 16))
}

function lerp(a, b, t) {
  return Math.round(a + (b - a) * t)
}

/** percent: day/gain change percent. cap: the percent at which the color
 * reaches full saturation (Finviz-style heatmaps typically cap around
 * ±3-5% for day change). */
export function divergingHeatColor(percent, cap = 4) {
  const negative = hexToRgb(readColor('--critical', '#c0392b'))
  const positive = hexToRgb(readColor('--good', '#147a4a'))
  const neutral = hexToRgb(readColor('--border-strong', '#8b8f99'))

  if (percent == null || Number.isNaN(percent)) {
    return `rgb(${neutral.join(', ')})`
  }

  const t = Math.max(-1, Math.min(1, percent / cap))
  const target = t < 0 ? negative : positive
  const magnitude = Math.abs(t)
  const [r, g, b] = neutral.map((channel, i) => lerp(channel, target[i], magnitude))
  return `rgb(${r}, ${g}, ${b})`
}
