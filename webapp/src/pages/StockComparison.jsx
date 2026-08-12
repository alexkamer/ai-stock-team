import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getJSON } from '../api/client'
import RowCompareChart from '../components/RowCompareChart'
import './StockComparison.css'

const SERIES_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']

function parseSymbols(searchParams) {
  const raw = searchParams.get('stocks')
  if (!raw) return []
  return [...new Set(raw.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean))]
}

function formatCompact(n) {
  if (n == null) return null
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  return n.toFixed(2)
}

function formatDividend(rate, yieldPct) {
  if (rate == null && yieldPct == null) return null
  const ratePart = rate != null ? `$${rate.toFixed(2)}` : '—'
  const yieldPart = yieldPct != null ? `(${yieldPct.toFixed(2)}%)` : ''
  return `${ratePart} ${yieldPart}`.trim()
}

const OVERVIEW_ROWS = [
  {
    key: 'market_cap',
    label: 'Market value',
    get: (t) => (t.market_cap != null ? `$${formatCompact(t.market_cap)}` : null),
    metric: 'market_cap',
    chartFormat: (v) => `$${formatCompact(v)}`,
  },
  {
    key: 'enterprise_value',
    label: 'Enterprise value',
    get: (t) => (t.enterprise_value != null ? `$${formatCompact(t.enterprise_value)}` : null),
    metric: 'enterprise_value',
    chartFormat: (v) => `$${formatCompact(v)}`,
  },
  {
    key: 'pe_ratio',
    label: 'Price to earnings',
    get: (t) => (t.pe_ratio != null ? t.pe_ratio.toFixed(1) : null),
    metric: 'pe_ratio',
    chartFormat: (v) => v.toFixed(1),
  },
  {
    key: 'diluted_eps',
    label: 'Diluted EPS',
    get: (t) => (t.diluted_eps != null ? `$${t.diluted_eps.toFixed(2)}` : null),
    metric: 'diluted_eps',
    chartFormat: (v) => `$${v.toFixed(2)}`,
    // Reported quarterly income-statement data, not derived from price -
    // there's no monthly granularity to switch to.
    fixedQuarterly: true,
  },
  {
    key: 'dividend',
    label: 'Forward dividend & yield',
    get: (t) => formatDividend(t.dividend_rate, t.dividend_yield) ?? 'None',
    metric: 'dividend_yield',
    chartFormat: (v) => `${v.toFixed(2)}%`,
  },
  { key: 'sector', label: 'Sector', get: (t) => t.sector ?? null },
  { key: 'industry', label: 'Industry', get: (t) => t.industry ?? null },
  { key: 'ceo', label: 'CEO', get: (t) => t.ceo ?? null },
]

function signedPct(n) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

const PERFORMANCE_ROWS = [
  { key: '1_week', label: '1 Week', get: (t) => (t.price_performance?.['1_week'] != null ? signedPct(t.price_performance['1_week']) : null), signed: true },
  { key: '3_month', label: '3 Months', get: (t) => (t.price_performance?.['3_month'] != null ? signedPct(t.price_performance['3_month']) : null), signed: true },
  { key: 'ytd', label: 'YTD', get: (t) => (t.price_performance?.ytd != null ? signedPct(t.price_performance.ytd) : null), signed: true },
  { key: '1_year', label: '1 Year', get: (t) => (t.price_performance?.['1_year'] != null ? signedPct(t.price_performance['1_year']) : null), signed: true },
]

const INCOME_STATEMENT_ROWS = [
  { key: 'revenue', label: 'Revenue', get: (t) => (t.income_statement?.revenue != null ? `$${formatCompact(t.income_statement.revenue)}` : null) },
  {
    key: 'operating_expenses',
    label: 'Operating Expenses',
    get: (t) => (t.income_statement?.operating_expenses != null ? `$${formatCompact(t.income_statement.operating_expenses)}` : null),
  },
  {
    key: 'operating_income',
    label: 'Operating Income',
    get: (t) => (t.income_statement?.operating_income != null ? `$${formatCompact(t.income_statement.operating_income)}` : null),
  },
  {
    key: 'revenue_growth_yoy',
    label: 'Revenue Growth YoY',
    get: (t) => (t.income_statement?.revenue_growth_yoy != null ? signedPct(t.income_statement.revenue_growth_yoy) : null),
    signed: true,
  },
  {
    key: 'gross_profit',
    label: 'Gross Profit',
    get: (t) => (t.income_statement?.gross_profit != null ? `$${formatCompact(t.income_statement.gross_profit)}` : null),
  },
]

const CASH_FLOW_ROWS = [
  {
    key: 'operating_cash_flow',
    label: 'Cash Flow from Operations',
    get: (t) => (t.cash_flow_statement?.operating_cash_flow != null ? `$${formatCompact(t.cash_flow_statement.operating_cash_flow)}` : null),
  },
  {
    key: 'capital_expenditures',
    label: 'Capital Expenditures',
    get: (t) => (t.cash_flow_statement?.capital_expenditures != null ? `$${formatCompact(t.cash_flow_statement.capital_expenditures)}` : null),
  },
  {
    key: 'investing_cash_flow',
    label: 'Cash from Investing Activities',
    get: (t) => (t.cash_flow_statement?.investing_cash_flow != null ? `$${formatCompact(t.cash_flow_statement.investing_cash_flow)}` : null),
  },
  {
    key: 'free_cash_flow',
    label: 'Free Cash Flow',
    get: (t) => (t.cash_flow_statement?.free_cash_flow != null ? `$${formatCompact(t.cash_flow_statement.free_cash_flow)}` : null),
  },
]

function CollapsibleTable({ title, tickers, rows, isOpen, onToggle }) {
  return (
    <div className="card stock-comparison__table">
      <button
        type="button"
        className={`stock-comparison__section-toggle${isOpen ? ' stock-comparison__section-toggle--open' : ''}`}
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <svg width="12" height="12" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 1 L8 5 L2 9" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {title}
      </button>
      {isOpen && (
        <table>
          <thead>
            <tr>
              <th />
              {tickers.map((t) => (
                <th key={t.ticker}>{t.ticker}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.label}</th>
                {tickers.map((t) => {
                  const value = row.get(t)
                  const good = row.signed && value != null ? value.startsWith('+') : null
                  return (
                    <td
                      key={t.ticker}
                      className={`num${good == null ? '' : good ? ' stock-comparison__good' : ' stock-comparison__bad'}`}
                    >
                      {value ?? '—'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function StockComparison() {
  const [searchParams, setSearchParams] = useSearchParams()
  const symbols = parseSymbols(searchParams)
  const [input, setInput] = useState('')
  const [quotes, setQuotes] = useState({})
  const [error, setError] = useState(null)
  const [expandedRow, setExpandedRow] = useState(null)
  const [performanceOpen, setPerformanceOpen] = useState(false)
  const [incomeStatementOpen, setIncomeStatementOpen] = useState(false)
  const [cashFlowOpen, setCashFlowOpen] = useState(false)
  const [interval, setInterval_] = useState('1mo')
  const [rowHistory, setRowHistory] = useState({})

  useEffect(() => {
    if (symbols.length === 0) return
    let cancelled = false
    getJSON(`/tickers/compare?symbols=${symbols.join(',')}`)
      .then((data) => {
        if (cancelled) return
        setError(null)
        setQuotes((prev) => {
          const next = { ...prev }
          for (const q of data) next[q.ticker] = q
          return next
        })
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols.join(',')])

  useEffect(() => {
    const row = OVERVIEW_ROWS.find((r) => r.key === expandedRow)
    if (!row?.metric || symbols.length === 0) return
    const effectiveInterval = row.fixedQuarterly ? '3mo' : interval
    const cacheKey = `${row.key}:${effectiveInterval}`
    let cancelled = false
    getJSON(`/tickers/compare/history?symbols=${symbols.join(',')}&metric=${row.metric}&interval=${effectiveInterval}`)
      .then((data) => {
        if (cancelled) return
        setRowHistory((prev) => ({ ...prev, [cacheKey]: data }))
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedRow, interval, symbols.join(',')])

  function addSymbol(e) {
    e.preventDefault()
    const symbol = input.trim().toUpperCase()
    if (!symbol || symbols.includes(symbol)) return
    setSearchParams({ stocks: [...symbols, symbol].join(',') })
    setInput('')
  }

  function removeSymbol(symbol) {
    const next = symbols.filter((s) => s !== symbol)
    if (next.length > 0) {
      setSearchParams({ stocks: next.join(',') })
    } else {
      setSearchParams({})
    }
    setQuotes((prev) => {
      const { [symbol]: _omit, ...rest } = prev
      return rest
    })
  }

  const tickers = symbols.map((s) => quotes[s]).filter(Boolean)
  const loading = symbols.length > 0 && tickers.length < symbols.length
  const colorOf = (ticker) => SERIES_COLORS[symbols.indexOf(ticker) % SERIES_COLORS.length]

  return (
    <div className="stock-comparison">
      <div className="stock-comparison__header">
        <span className="eyebrow">Research</span>
        <h1>Stock comparison</h1>
      </div>

      <form className="stock-comparison__add" onSubmit={addSymbol}>
        <input
          type="text"
          placeholder="Add a ticker (e.g. NVDA)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          aria-label="Add ticker to compare"
        />
        <button type="submit">Add</button>
      </form>

      {symbols.length > 0 && (
        <div className="stock-comparison__chips">
          {symbols.map((s) => (
            <span key={s} className="stock-comparison__chip">
              {s}
              <button type="button" onClick={() => removeSymbol(s)} aria-label={`Remove ${s}`}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {error && <div className="error-banner">Failed to load comparison: {error}</div>}

      {symbols.length === 0 ? (
        <p className="stock-comparison__empty">Add two or more tickers above to compare them.</p>
      ) : symbols.length === 1 ? (
        <p className="stock-comparison__empty">Add at least one more ticker to compare.</p>
      ) : loading ? (
        <div className="stock-comparison__row stock-comparison__row--loading" />
      ) : (
        <div className="card stock-comparison__table">
          <table>
            <thead>
              <tr>
                <th />
                {tickers.map((t) => (
                  <th key={t.ticker}>{t.ticker}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {OVERVIEW_ROWS.filter((row) => tickers.some((t) => row.get(t) != null)).map((row) => {
                const isExpanded = expandedRow === row.key
                return (
                  <Fragment key={row.key}>
                    <tr>
                      <th scope="row">
                        {row.metric ? (
                          <button
                            type="button"
                            className={`stock-comparison__row-toggle${isExpanded ? ' stock-comparison__row-toggle--open' : ''}`}
                            onClick={() => setExpandedRow(isExpanded ? null : row.key)}
                            aria-expanded={isExpanded}
                            aria-label={`${isExpanded ? 'Hide' : 'Show'} ${row.label} chart`}
                          >
                            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                              <path d="M2 1 L8 5 L2 9" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            {row.label}
                          </button>
                        ) : (
                          row.label
                        )}
                      </th>
                      {tickers.map((t) => (
                        <td key={t.ticker}>{row.get(t) ?? '—'}</td>
                      ))}
                    </tr>
                    {row.metric && isExpanded && (
                      <tr className="stock-comparison__chart-row">
                        <td colSpan={tickers.length + 1}>
                          <RowCompareChart
                            series={symbols
                              .map((s) =>
                                (rowHistory[`${row.key}:${row.fixedQuarterly ? '3mo' : interval}`] ?? []).find(
                                  (h) => h.ticker === s
                                )
                              )
                              .filter(Boolean)}
                            formatValue={row.chartFormat}
                            colorOf={colorOf}
                            interval={interval}
                            onIntervalChange={row.fixedQuarterly ? null : setInterval_}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {symbols.length > 1 && !loading && (
        <CollapsibleTable
          title="Price Performance"
          tickers={tickers}
          rows={PERFORMANCE_ROWS}
          isOpen={performanceOpen}
          onToggle={() => setPerformanceOpen((prev) => !prev)}
        />
      )}

      {symbols.length > 1 && !loading && (
        <CollapsibleTable
          title="Income Statement"
          tickers={tickers}
          rows={INCOME_STATEMENT_ROWS}
          isOpen={incomeStatementOpen}
          onToggle={() => setIncomeStatementOpen((prev) => !prev)}
        />
      )}

      {symbols.length > 1 && !loading && (
        <CollapsibleTable
          title="Cash Flow"
          tickers={tickers}
          rows={CASH_FLOW_ROWS}
          isOpen={cashFlowOpen}
          onToggle={() => setCashFlowOpen((prev) => !prev)}
        />
      )}
    </div>
  )
}
