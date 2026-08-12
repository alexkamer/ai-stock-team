import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { WatchlistProvider, useWatchlist } from './WatchlistContext'

function TestConsumer() {
  const { tickers, addTicker, removeTicker } = useWatchlist()
  return (
    <div>
      <div data-testid="tickers">{tickers.join(',')}</div>
      <button onClick={() => addTicker('tsla')}>add tsla</button>
      <button onClick={() => removeTicker('AAPL')}>remove aapl</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <WatchlistProvider>
      <TestConsumer />
    </WatchlistProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
})

describe('WatchlistProvider', () => {
  it('defaults to the fixed starter list on first visit', () => {
    renderProvider()
    expect(screen.getByTestId('tickers').textContent).toBe('NVDA,AAPL,MSFT,GOOGL,AMZN')
  })

  it('adds a ticker, uppercased', () => {
    renderProvider()
    act(() => screen.getByText('add tsla').click())
    expect(screen.getByTestId('tickers').textContent).toContain('TSLA')
  })

  it('does not add a duplicate ticker', () => {
    renderProvider()
    act(() => screen.getByText('add tsla').click())
    act(() => screen.getByText('add tsla').click())
    const tickers = screen.getByTestId('tickers').textContent.split(',')
    expect(tickers.filter((t) => t === 'TSLA')).toHaveLength(1)
  })

  it('removes a ticker', () => {
    renderProvider()
    act(() => screen.getByText('remove aapl').click())
    expect(screen.getByTestId('tickers').textContent).not.toContain('AAPL')
  })

  it('persists changes to localStorage', () => {
    renderProvider()
    act(() => screen.getByText('add tsla').click())
    expect(JSON.parse(localStorage.getItem('watchlist'))).toContain('TSLA')
  })

  it('restores a saved list from localStorage instead of the default', () => {
    localStorage.setItem('watchlist', JSON.stringify(['TSLA', 'AMD']))
    renderProvider()
    expect(screen.getByTestId('tickers').textContent).toBe('TSLA,AMD')
  })
})
