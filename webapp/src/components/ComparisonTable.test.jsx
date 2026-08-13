import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ComparisonTable from './ComparisonTable'

describe('ComparisonTable', () => {
  it('renders a column per ticker and a row per stat both have', () => {
    render(
      <ComparisonTable
        tickers={[
          { ticker: 'AAPL', price: 301.58, dayChangePercent: -1.09 },
          { ticker: 'NVDA', price: 223.93, dayChangePercent: 2.94 },
        ]}
        onClear={() => {}}
      />
    )
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText('NVDA')).toBeInTheDocument()
    expect(screen.getByText('301.58')).toBeInTheDocument()
    expect(screen.getByText('223.93')).toBeInTheDocument()
  })

  it('omits a stat row entirely when neither ticker has it', () => {
    render(
      <ComparisonTable tickers={[{ ticker: 'AAPL', price: 301.58 }, { ticker: 'NVDA', price: 223.93 }]} onClear={() => {}} />
    )
    expect(screen.queryByText('P/E ratio')).not.toBeInTheDocument()
  })

  it('shows a stat row if at least one ticker has it, with — for the other', () => {
    render(
      <ComparisonTable
        tickers={[{ ticker: 'AAPL', price: 301.58, peRatio: 34.6 }, { ticker: 'NVDA', price: 223.93 }]}
        onClear={() => {}}
      />
    )
    expect(screen.getByText('P/E ratio')).toBeInTheDocument()
    expect(screen.getByText('34.6')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('calls onClear when the clear button is clicked', () => {
    const onClear = vi.fn()
    render(<ComparisonTable tickers={[{ ticker: 'AAPL', price: 1 }, { ticker: 'NVDA', price: 2 }]} onClear={onClear} />)
    screen.getByText('Clear').click()
    expect(onClear).toHaveBeenCalled()
  })
})
