// Squarified treemap (Bruls, Huizing, van Wijk 1999): lays out `items` (each
// with a positive `value`) into a rect, minimizing how thin/sliver-shaped
// tiles get, so a 70-holding portfolio stays legible instead of degenerating
// into one-pixel-wide strips the way a naive slice-by-value layout would.
export function squarify(items, x, y, width, height) {
  const sorted = [...items].sort((a, b) => b.value - a.value)
  const total = sorted.reduce((sum, item) => sum + item.value, 0)
  if (total <= 0 || width <= 0 || height <= 0) return []

  const area = width * height
  const scaled = sorted.map((item) => ({ ...item, area: (item.value / total) * area }))
  return layout(scaled, x, y, width, height)
}

function layout(items, x, y, width, height) {
  if (items.length === 0) return []
  if (items.length === 1) {
    return [{ ...items[0], x, y, width, height }]
  }

  const shortSide = Math.min(width, height)
  let row = items.slice(0, 1)
  let i = 1
  while (i < items.length) {
    const candidate = items.slice(0, i + 1)
    if (worstAspectRatio(candidate, shortSide) <= worstAspectRatio(row, shortSide)) {
      row = candidate
      i++
    } else {
      break
    }
  }

  const rowArea = row.reduce((sum, item) => sum + item.area, 0)
  const rest = items.slice(row.length)
  const placed = []

  if (width >= height) {
    const rowWidth = rowArea / height
    let rowY = y
    for (const item of row) {
      const itemHeight = item.area / rowWidth
      placed.push({ ...item, x, y: rowY, width: rowWidth, height: itemHeight })
      rowY += itemHeight
    }
    placed.push(...layout(rest, x + rowWidth, y, width - rowWidth, height))
  } else {
    const rowHeight = rowArea / width
    let rowX = x
    for (const item of row) {
      const itemWidth = item.area / rowHeight
      placed.push({ ...item, x: rowX, y, width: itemWidth, height: rowHeight })
      rowX += itemWidth
    }
    placed.push(...layout(rest, x, y + rowHeight, width, height - rowHeight))
  }
  return placed
}

function worstAspectRatio(row, shortSide) {
  const sum = row.reduce((total, item) => total + item.area, 0)
  const maxArea = Math.max(...row.map((item) => item.area))
  const minArea = Math.min(...row.map((item) => item.area))
  return Math.max(
    (shortSide * shortSide * maxArea) / (sum * sum),
    (sum * sum) / (shortSide * shortSide * minArea)
  )
}
