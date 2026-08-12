// Builds ticker-aware quick-action suggestions from the canvas's current
// state for the most recently touched ticker - skips anything already known
// about that ticker so the chips always offer something new to ask, rather
// than repeating what's already on the card.

const HISTORY_PERIODS = [
  { label: '1mo history', period: '1mo' },
  { label: '6mo history', period: '6mo' },
  { label: '1y history', period: '1y' },
]

export function suggestionsFor(ticker) {
  if (!ticker) return []
  const suggestions = []

  if (ticker.marketCap == null) {
    suggestions.push({ key: 'market_cap', label: 'Market cap', text: `What's ${ticker.ticker}'s market cap?` })
  }
  if (ticker.peRatio == null) {
    suggestions.push({ key: 'pe_ratio', label: 'P/E ratio', text: `What's ${ticker.ticker}'s P/E ratio?` })
  }

  const knownPeriod = ticker.history?.period
  const nextPeriod = HISTORY_PERIODS.find((p) => p.period !== knownPeriod)
  if (nextPeriod) {
    suggestions.push({
      key: `history_${nextPeriod.period}`,
      label: nextPeriod.label,
      text: `How has ${ticker.ticker} moved over the past ${nextPeriod.period === '1mo' ? 'month' : nextPeriod.period === '6mo' ? '6 months' : 'year'}?`,
    })
  }

  suggestions.push({
    key: 'news',
    label: 'Recent news',
    text: `What's the recent news on ${ticker.ticker}?`,
  })

  return suggestions.slice(0, 3)
}
