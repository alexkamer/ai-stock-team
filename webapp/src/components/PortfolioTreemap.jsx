import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { derivePositionRow } from './positionRow'
import { squarify } from './treemapLayout'
import { divergingHeatColor } from './heatColor'
import './PortfolioTreemap.css'

// Below this "side" (sqrt(width*height), i.e. the side of an equal-area
// square - a size measure that works for both tall and wide slivers), a
// tile gets no label at all; a 70-holding portfolio has plenty of these.
const MIN_SIDE_FOR_ANY_LABEL = 26
const MIN_READABLE_FONT = 9
const TILE_TEXT_PADDING = 8
// Rough average glyph width for a bold sans ticker symbol, as a fraction
// of font-size - used to shrink text to fit a tile's actual width rather
// than relying on the size-from-area heuristic alone, which can't tell a
// wide tile with a long symbol from a narrow one with a short symbol.
const AVG_CHAR_WIDTH_FACTOR = 0.62

function useContainerWidth(ref) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    setWidth(el.clientWidth)
    return () => observer.disconnect()
  }, [ref])
  return width
}

// Shrinks fontSize, if needed, so `text` doesn't overflow `maxWidth` at the
// estimated glyph width - returns null if even the minimum readable size
// wouldn't fit (caller should skip the label entirely rather than render
// something illegibly small or rely solely on clipping to hide overflow).
function fitFontSize(text, maxWidth, desiredSize) {
  const usableWidth = maxWidth - TILE_TEXT_PADDING
  const maxByWidth = usableWidth / Math.max(1, text.length) / AVG_CHAR_WIDTH_FACTOR
  const size = Math.min(desiredSize, maxByWidth)
  return size >= MIN_READABLE_FONT ? size : null
}

/** Size = market value, color = today's % change (red -> gray -> green) -
 * one view for both composition and performance across every holding,
 * which a 70+ position portfolio makes unreadable as a pie chart. A wide
 * rectangle that fills the container's actual pixel width (ResizeObserver)
 * with a proportional height, so it tracks the window on resize; each
 * tile's label is sized to its own footprint and clipped to its rect so
 * text never spills across a tile boundary. */
export default function PortfolioTreemap({ positions }) {
  const navigate = useNavigate()
  const containerRef = useRef(null)
  const width = useContainerWidth(containerRef)
  const height = Math.round(Math.max(240, Math.min(460, width * 0.34)))
  const [hovered, setHovered] = useState(null)

  const tiles = useMemo(() => {
    if (!width) return []
    const rows = positions.map(derivePositionRow).filter((row) => row.value != null && row.value > 0)
    return squarify(rows, 0, 0, width, height)
  }, [positions, width, height])

  return (
    <div className="portfolio-treemap" ref={containerRef}>
      {tiles.length > 0 && (
        <svg
          className="portfolio-treemap__svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Portfolio holdings sized by market value and colored by today's price change"
        >
          <defs>
            {tiles.map((tile, i) => (
              <clipPath key={i} id={`treemap-clip-${i}`}>
                <rect x={tile.x} y={tile.y} width={tile.width} height={tile.height} />
              </clipPath>
            ))}
          </defs>

          {tiles.map((tile, i) => {
            const eventHandlers = {
              onMouseEnter: () => setHovered(tile),
              onMouseLeave: () => setHovered((current) => (current?.symbol === tile.symbol ? null : current)),
              onClick: () => navigate(`/tickers/${tile.symbol}`),
            }

            const side = Math.sqrt(tile.width * tile.height)
            const symbolSize =
              side >= MIN_SIDE_FOR_ANY_LABEL
                ? fitFontSize(tile.symbol, tile.width, Math.min(40, Math.max(13, side * 0.3), tile.height * 0.7))
                : null

            if (symbolSize == null) {
              return (
                <rect
                  key={tile.symbol}
                  className="portfolio-treemap__tile-rect"
                  x={tile.x}
                  y={tile.y}
                  width={tile.width}
                  height={tile.height}
                  fill={divergingHeatColor(tile.dayChangePercent)}
                  {...eventHandlers}
                />
              )
            }

            const changeText =
              tile.dayChangePercent == null
                ? '—'
                : `${tile.dayChangePercent >= 0 ? '+' : ''}${tile.dayChangePercent.toFixed(1)}%`
            const changeSize =
              tile.height >= symbolSize * 1.9 + 14
                ? fitFontSize(changeText, tile.width, symbolSize * 0.6)
                : null

            return (
              <g key={tile.symbol} className="portfolio-treemap__tile" {...eventHandlers}>
                <rect
                  x={tile.x}
                  y={tile.y}
                  width={tile.width}
                  height={tile.height}
                  fill={divergingHeatColor(tile.dayChangePercent)}
                />
                <g clipPath={`url(#treemap-clip-${i})`}>
                  <text
                    x={tile.x + tile.width / 2}
                    y={tile.y + tile.height / 2 - (changeSize ? symbolSize * 0.35 : 0)}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    className="portfolio-treemap__symbol"
                    style={{ fontSize: `${symbolSize}px` }}
                  >
                    {tile.symbol}
                  </text>
                  {changeSize && (
                    <text
                      x={tile.x + tile.width / 2}
                      y={tile.y + tile.height / 2 + symbolSize * 0.55}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="portfolio-treemap__change"
                      style={{ fontSize: `${changeSize}px` }}
                    >
                      {changeText}
                    </text>
                  )}
                </g>
              </g>
            )
          })}
        </svg>
      )}

      {hovered && (
        <div className="portfolio-treemap__tooltip">
          <span className="portfolio-treemap__tooltip-symbol">{hovered.symbol}</span>
          {hovered.description && <span className="portfolio-treemap__tooltip-description">{hovered.description}</span>}
          <span className="num">Shares {hovered.units}</span>
          <span className="num">Value {hovered.value.toFixed(2)}</span>
          <span className={`num ${hovered.dayChangeDollar == null ? '' : hovered.dayChangeDollar >= 0 ? 'text-good' : 'text-critical'}`}>
            Day {hovered.dayChangeDollar == null ? '—' : `${hovered.dayChangeDollar >= 0 ? '+' : ''}${hovered.dayChangeDollar.toFixed(2)}`}
            {hovered.dayChangePercent != null && ` (${hovered.dayChangePercent >= 0 ? '+' : ''}${hovered.dayChangePercent.toFixed(2)}%)`}
          </span>
          {hovered.gainDollar != null && (
            <span className={`num ${hovered.gainDollar >= 0 ? 'text-good' : 'text-critical'}`}>
              Gain {hovered.gainDollar >= 0 ? '+' : ''}
              {hovered.gainDollar.toFixed(2)} ({hovered.gainPercent >= 0 ? '+' : ''}
              {hovered.gainPercent.toFixed(1)}%)
            </span>
          )}
        </div>
      )}
    </div>
  )
}
