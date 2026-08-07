import './ToolCallPill.css'

const TOOL_LABELS = {
  get_stock_price: 'Checking price',
  get_market_cap: 'Checking market cap',
  get_pe_ratio: 'Checking P/E ratio',
  get_company_name: 'Looking up company',
  get_day_change: 'Checking day change',
  get_price_history: 'Checking price history',
  get_sparkline_prices: 'Checking price history',
  get_news_headlines: 'Checking news',
  get_watchlist_prices: 'Checking watchlist',
  get_fundamentals: 'Consulting fundamentals specialist',
  get_sentiment: 'Consulting sentiment specialist',
}

function labelFor(toolName) {
  return TOOL_LABELS[toolName] ?? `Running ${toolName}`
}

/** One pill per tool call, "in flight" until its matching result arrives. */
export default function ToolCallPill({ toolName, done }) {
  return (
    <span className={`tool-pill${done ? ' tool-pill--done' : ''}`}>
      <span className="tool-pill__spinner" aria-hidden="true" />
      {labelFor(toolName)}
      {done ? '' : '…'}
    </span>
  )
}
