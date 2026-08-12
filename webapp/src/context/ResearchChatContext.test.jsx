import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ResearchChatProvider, useResearchChat } from './ResearchChatContext'
import { WatchlistProvider } from './WatchlistContext'
import { getJSON, streamSSE } from '../api/client'

vi.mock('../api/client', () => ({
  getJSON: vi.fn(),
  streamSSE: vi.fn(),
}))

function TestConsumer() {
  const { messages, tickers, error, sendMessage } = useResearchChat()
  return (
    <div>
      <button onClick={() => sendMessage("what's AAPL's price")}>ask</button>
      <div data-testid="message-count">{messages.length}</div>
      <div data-testid="assistant-text">{messages.find((m) => m.role === 'assistant')?.text ?? ''}</div>
      <div data-testid="assistant-error">{messages.find((m) => m.role === 'assistant')?.error ?? ''}</div>
      <div data-testid="ticker-price">{tickers.AAPL?.price ?? ''}</div>
      <div data-testid="error">{error ?? ''}</div>
    </div>
  )
}

function renderProvider() {
  return render(
    <WatchlistProvider>
      <ResearchChatProvider>
        <TestConsumer />
      </ResearchChatProvider>
    </WatchlistProvider>
  )
}

// Drives streamSSE's onEvent callback with a scripted sequence of SSE events,
// the same shape the real backend sends over /chat.
function mockStream(events) {
  streamSSE.mockImplementation(async (path, { onEvent }) => {
    for (const [name, data] of events) onEvent(name, data)
  })
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  getJSON.mockResolvedValue([])
})

describe('ResearchChatProvider', () => {
  it('appends a user message immediately and streams the assistant reply in', async () => {
    mockStream([
      ['session', { session_id: 's1' }],
      ['text', { delta: 'AAPL is ' }],
      ['text', { delta: 'at $150.' }],
    ])
    renderProvider()

    act(() => screen.getByText('ask').click())

    await waitFor(() => expect(screen.getByTestId('assistant-text').textContent).toBe('AAPL is at $150.'))
    expect(screen.getByTestId('message-count').textContent).toBe('2')
  })

  it('folds a tool_result into the canvas keyed by the matching tool_call args', async () => {
    mockStream([
      ['session', { session_id: 's1' }],
      ['tool_call', { tool_name: 'get_stock_price', args: { ticker: 'AAPL' } }],
      ['tool_result', { tool_name: 'get_stock_price', content: 150.5 }],
    ])
    renderProvider()

    act(() => screen.getByText('ask').click())

    await waitFor(() => expect(screen.getByTestId('ticker-price').textContent).toBe('150.5'))
  })

  it('attaches a tool error to the assistant message it happened on, not the global banner', async () => {
    mockStream([
      ['session', { session_id: 's1' }],
      ['error', { detail: 'No price found for ticker BADTICKER' }],
    ])
    renderProvider()

    act(() => screen.getByText('ask').click())

    await waitFor(() =>
      expect(screen.getByTestId('assistant-error').textContent).toBe('No price found for ticker BADTICKER')
    )
    expect(screen.getByTestId('error').textContent).toBe('')
  })

  it('surfaces a connection failure as the global banner, not a per-message error', async () => {
    streamSSE.mockRejectedValue(new Error('Request failed: 500'))
    renderProvider()

    act(() => screen.getByText('ask').click())

    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('Request failed: 500'))
    expect(screen.getByTestId('assistant-error').textContent).toBe('')
  })

  it('fetches a baseline quote for any ticker mentioned in a tool_call, even if never asked about directly', async () => {
    mockStream([
      ['session', { session_id: 's1' }],
      ['tool_call', { tool_name: 'get_pe_ratio', args: { ticker: 'NVDA' } }],
      ['tool_result', { tool_name: 'get_pe_ratio', content: 34.5 }],
    ])
    getJSON.mockResolvedValue([{ company_name: 'NVIDIA Corporation', price: 223.93 }])
    renderProvider()

    act(() => screen.getByText('ask').click())

    await waitFor(() => expect(getJSON).toHaveBeenCalledWith('/watchlist?symbols=NVDA'))
  })

  it('persists messages and tickers to localStorage after a send completes', async () => {
    mockStream([
      ['session', { session_id: 's1' }],
      ['tool_call', { tool_name: 'get_stock_price', args: { ticker: 'AAPL' } }],
      ['tool_result', { tool_name: 'get_stock_price', content: 150.5 }],
      ['text', { delta: 'done' }],
    ])
    renderProvider()

    act(() => screen.getByText('ask').click())
    await waitFor(() => expect(screen.getByTestId('ticker-price').textContent).toBe('150.5'))

    const stored = JSON.parse(localStorage.getItem('research-chat-state'))
    expect(stored.tickers.AAPL.price).toBe(150.5)
    expect(stored.sessionId).toBe('s1')
    expect(stored.messages).toHaveLength(2)
  })

  it('passes the current watchlist along on every send', async () => {
    localStorage.setItem('watchlist', JSON.stringify(['TSLA', 'AMD']))
    mockStream([['session', { session_id: 's1' }]])
    renderProvider()

    act(() => screen.getByText('ask').click())
    await waitFor(() => expect(streamSSE).toHaveBeenCalled())

    const [, options] = streamSSE.mock.calls[0]
    expect(options.body.watchlist).toEqual(['TSLA', 'AMD'])
  })

  it('restores a prior conversation from localStorage on mount', () => {
    localStorage.setItem(
      'research-chat-state',
      JSON.stringify({
        messages: [{ id: 1, role: 'user', text: 'hi' }],
        tickers: { AAPL: { ticker: 'AAPL', price: 150.5, seq: 1 } },
        sessionId: 's1',
      })
    )

    renderProvider()

    expect(screen.getByTestId('message-count').textContent).toBe('1')
    expect(screen.getByTestId('ticker-price').textContent).toBe('150.5')
  })
})
