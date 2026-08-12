import { describe, expect, it } from 'vitest'
import { suggestionsFor } from './suggestions'

describe('suggestionsFor', () => {
  it('returns nothing for no ticker', () => {
    expect(suggestionsFor(undefined)).toEqual([])
  })

  it('suggests market cap and P/E when neither is known yet', () => {
    const labels = suggestionsFor({ ticker: 'AAPL' }).map((s) => s.label)
    expect(labels).toContain('Market cap')
    expect(labels).toContain('P/E ratio')
  })

  it('omits market cap once it is already on the card', () => {
    const labels = suggestionsFor({ ticker: 'AAPL', marketCap: 3e12 }).map((s) => s.label)
    expect(labels).not.toContain('Market cap')
  })

  it('omits P/E once it is already on the card', () => {
    const labels = suggestionsFor({ ticker: 'AAPL', peRatio: 34.5 }).map((s) => s.label)
    expect(labels).not.toContain('P/E ratio')
  })

  it('suggests a history period different from the one already fetched', () => {
    const labels = suggestionsFor({ ticker: 'AAPL', history: { period: '1mo' } }).map((s) => s.label)
    expect(labels).not.toContain('1mo history')
    expect(labels.some((l) => l.includes('history'))).toBe(true)
  })

  it('caps suggestions at 3', () => {
    const suggestions = suggestionsFor({ ticker: 'AAPL' })
    expect(suggestions.length).toBeLessThanOrEqual(3)
  })

  it('every suggestion carries a ready-to-send question mentioning the ticker', () => {
    const suggestions = suggestionsFor({ ticker: 'NVDA' })
    for (const s of suggestions) {
      expect(s.text).toContain('NVDA')
    }
  })
})
