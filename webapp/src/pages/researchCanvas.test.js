import { describe, expect, it } from 'vitest'
import { applyBaseline, applyToolResult } from './researchCanvas'

describe('applyToolResult', () => {
  it('ignores tool calls with no ticker arg', () => {
    const result = applyToolResult({}, 'get_stock_price', {}, 150)
    expect(result).toEqual({})
  })

  it('ignores unknown tool names', () => {
    const result = applyToolResult({}, 'get_news_headlines', { ticker: 'AAPL' }, ['headline'])
    expect(result).toEqual({})
  })

  it('records a price under the uppercased ticker', () => {
    const result = applyToolResult({}, 'get_stock_price', { ticker: 'aapl' }, 150.5)
    expect(result.AAPL.price).toBe(150.5)
    expect(result.AAPL.ticker).toBe('AAPL')
  })

  it('splits get_day_change into percent and absolute fields', () => {
    const result = applyToolResult({}, 'get_day_change', { ticker: 'AAPL' }, { percent: -1.09, absolute: -3.33 })
    expect(result.AAPL.dayChangePercent).toBe(-1.09)
    expect(result.AAPL.dayChangeAbs).toBe(-3.33)
  })

  it('stores get_price_history results under history', () => {
    const history = { period: '1mo', start_price: 317, end_price: 301, percent_change: -5 }
    const result = applyToolResult({}, 'get_price_history', { ticker: 'AAPL' }, history)
    expect(result.AAPL.history).toEqual(history)
  })

  it('accumulates separate fields for the same ticker across calls instead of overwriting the card', () => {
    let tickers = applyToolResult({}, 'get_stock_price', { ticker: 'AAPL' }, 150)
    tickers = applyToolResult(tickers, 'get_pe_ratio', { ticker: 'AAPL' }, 34.5)
    expect(tickers.AAPL.price).toBe(150)
    expect(tickers.AAPL.peRatio).toBe(34.5)
  })

  it('keeps separate tickers independent', () => {
    let tickers = applyToolResult({}, 'get_stock_price', { ticker: 'AAPL' }, 150)
    tickers = applyToolResult(tickers, 'get_market_cap', { ticker: 'NVDA' }, 5.4e12)
    expect(tickers.AAPL.marketCap).toBeUndefined()
    expect(tickers.NVDA.price).toBeUndefined()
    expect(tickers.NVDA.marketCap).toBe(5.4e12)
  })

  it('fans get_watchlist_prices out across every ticker in the result', () => {
    const result = applyToolResult({}, 'get_watchlist_prices', {}, { nvda: 223.9, aapl: 301.6 })
    expect(result.NVDA.price).toBe(223.9)
    expect(result.AAPL.price).toBe(301.6)
  })

  it('ignores a malformed get_watchlist_prices result', () => {
    const result = applyToolResult({}, 'get_watchlist_prices', {}, null)
    expect(result).toEqual({})
  })

  it('advances seq on every call so the most recently touched ticker can be sorted first', () => {
    let tickers = applyToolResult({}, 'get_stock_price', { ticker: 'AAPL' }, 150)
    const firstSeq = tickers.AAPL.seq
    tickers = applyToolResult(tickers, 'get_stock_price', { ticker: 'NVDA' }, 220)
    expect(tickers.NVDA.seq).toBeGreaterThan(firstSeq)
  })
})

describe('applyBaseline', () => {
  it('maps snake_case quote fields onto the card', () => {
    const quote = {
      company_name: 'Apple Inc.',
      price: 301.58,
      day_change_percent: -1.09,
      day_change_abs: -3.33,
      day_prices: [300, 301, 301.58],
    }
    const result = applyBaseline({}, 'AAPL', quote)
    expect(result.AAPL).toMatchObject({
      ticker: 'AAPL',
      companyName: 'Apple Inc.',
      price: 301.58,
      dayChangePercent: -1.09,
      dayChangeAbs: -3.33,
      dayPrices: [300, 301, 301.58],
    })
  })

  it('does not clobber fields a chat tool call already set on the same ticker', () => {
    const withChatData = applyToolResult({}, 'get_stock_price', { ticker: 'AAPL' }, 999.99)
    const result = applyBaseline(withChatData, 'AAPL', { company_name: 'Apple Inc.', price: 301.58 })
    // the live chat price wins over the baseline's price
    expect(result.AAPL.price).toBe(999.99)
    // but the baseline still fills in fields the chat call never touched
    expect(result.AAPL.companyName).toBe('Apple Inc.')
  })

  it('fills in a brand-new ticker the chat never explicitly asked about', () => {
    const result = applyBaseline({}, 'NVDA', { company_name: 'NVIDIA Corporation', price: 223.93 })
    expect(result.NVDA.companyName).toBe('NVIDIA Corporation')
    expect(result.NVDA.price).toBe(223.93)
  })
})
