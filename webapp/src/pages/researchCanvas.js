// Maps a chat tool call's (tool_name, args, result) onto the per-ticker
// canvas state - accumulated across the whole session, not just one message,
// so asking about AAPL five different ways fills in one AAPL card instead of
// scattering the data across scrollback.

function touch(tickers, ticker, patch) {
  const existing = tickers[ticker] ?? { ticker, seq: 0 }
  return { ...tickers, [ticker]: { ...existing, ...patch } }
}

let counter = 0

/**
 * Merges a /watchlist baseline quote into a ticker's card - name, price,
 * day change, day sparkline - without clobbering fields a chat tool call
 * has already set (e.g. a fresher get_stock_price beats the baseline's).
 */
export function applyBaseline(tickers, ticker, quote) {
  const existing = tickers[ticker] ?? { ticker, seq: 0 }
  const baseline = {
    ticker,
    companyName: quote.company_name,
    price: quote.price,
    dayChangePercent: quote.day_change_percent,
    dayChangeAbs: quote.day_change_abs,
    dayPrices: quote.day_prices,
  }
  return { ...tickers, [ticker]: { ...baseline, ...existing } }
}

/** Returns a new tickers map with `content` (a tool_result's already-JSON value) folded in. */
export function applyToolResult(tickers, toolName, args, content) {
  counter += 1
  const argTicker = args?.ticker?.toUpperCase()

  switch (toolName) {
    case 'get_stock_price':
      return argTicker ? touch(tickers, argTicker, { price: content, seq: counter }) : tickers
    case 'get_market_cap':
      return argTicker ? touch(tickers, argTicker, { marketCap: content, seq: counter }) : tickers
    case 'get_pe_ratio':
      return argTicker ? touch(tickers, argTicker, { peRatio: content, seq: counter }) : tickers
    case 'get_day_change':
      return argTicker
        ? touch(tickers, argTicker, {
            dayChangePercent: content?.percent,
            dayChangeAbs: content?.absolute,
            seq: counter,
          })
        : tickers
    case 'get_price_history':
      return argTicker ? touch(tickers, argTicker, { history: content, seq: counter }) : tickers
    case 'get_watchlist_prices':
      if (!content || typeof content !== 'object') return tickers
      let next = tickers
      for (const [ticker, price] of Object.entries(content)) {
        next = touch(next, ticker.toUpperCase(), { price, seq: counter })
      }
      return next
    default:
      return tickers
  }
}
