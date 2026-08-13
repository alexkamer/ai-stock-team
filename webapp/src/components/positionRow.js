// Normalizes a position from either /accounts/{id}/positions (has `price`,
// per-unit `cost_basis`) or /portfolio (has `value`, already-total
// `total_cost_basis`) into one shape a shared table can render.
export function derivePositionRow(position) {
  const units = position.units
  const price = position.price ?? (units ? position.value / units : null)
  const value = position.value ?? (price != null ? units * price : null)
  const costBasisTotal =
    position.total_cost_basis !== undefined
      ? position.total_cost_basis
      : position.cost_basis != null
        ? units * position.cost_basis
        : null
  const dayChangeDollar = position.price_change != null ? units * position.price_change : null
  const gainDollar = costBasisTotal != null && value != null ? value - costBasisTotal : null
  const gainPercent = gainDollar != null && costBasisTotal ? (gainDollar / costBasisTotal) * 100 : null

  return {
    symbol: position.symbol,
    description: position.description,
    units,
    price,
    priceChange: position.price_change ?? null,
    priceChangePercent: position.price_change_percent ?? null,
    value,
    dayChangeDollar,
    dayChangePercent: position.price_change_percent ?? null,
    costBasisTotal,
    gainDollar,
    gainPercent,
  }
}

export const POSITION_COLUMNS = [
  { key: 'symbol', label: 'Symbol' },
  { key: 'units', label: 'Qty' },
  { key: 'price', label: 'Price' },
  { key: 'priceChange', label: 'Price Chg $' },
  { key: 'priceChangePercent', label: 'Price Chg %' },
  { key: 'value', label: 'Market Value' },
  { key: 'dayChangeDollar', label: 'Day Chg $' },
  { key: 'dayChangePercent', label: 'Day Chg %' },
  { key: 'costBasisTotal', label: 'Cost Basis' },
  { key: 'gainDollar', label: 'Gain $' },
  { key: 'gainPercent', label: 'Gain %' },
]
