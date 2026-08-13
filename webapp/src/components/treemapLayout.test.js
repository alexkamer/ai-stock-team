import { describe, expect, it } from 'vitest'
import { squarify } from './treemapLayout'

describe('squarify', () => {
  it('gives a single item the whole rect', () => {
    const [tile] = squarify([{ id: 'a', value: 10 }], 0, 0, 100, 50)
    expect(tile).toMatchObject({ x: 0, y: 0, width: 100, height: 50 })
  })

  it('returns nothing for an empty or all-zero-value input', () => {
    expect(squarify([], 0, 0, 100, 50)).toEqual([])
    expect(squarify([{ id: 'a', value: 0 }], 0, 0, 100, 50)).toEqual([])
  })

  it('splits area proportionally to value', () => {
    const tiles = squarify(
      [
        { id: 'big', value: 75 },
        { id: 'small', value: 25 },
      ],
      0,
      0,
      100,
      100
    )
    const areaFor = (id) => tiles.find((t) => t.id === id).width * tiles.find((t) => t.id === id).height
    expect(areaFor('big')).toBeCloseTo(7500, 0)
    expect(areaFor('small')).toBeCloseTo(2500, 0)
  })

  it('tiles never overlap and stay within the outer rect', () => {
    const items = Array.from({ length: 12 }, (_, i) => ({ id: i, value: (i + 1) * 3.7 }))
    const tiles = squarify(items, 0, 0, 200, 120)

    for (const tile of tiles) {
      expect(tile.x).toBeGreaterThanOrEqual(0)
      expect(tile.y).toBeGreaterThanOrEqual(0)
      expect(tile.x + tile.width).toBeLessThanOrEqual(200.0001)
      expect(tile.y + tile.height).toBeLessThanOrEqual(120.0001)
    }

    const totalArea = tiles.reduce((sum, t) => sum + t.width * t.height, 0)
    expect(totalArea).toBeCloseTo(200 * 120, 0)
  })
})
