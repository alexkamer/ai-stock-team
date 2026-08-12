import { useState } from 'react'
import ToolCallPill from '../components/ToolCallPill'
import CanvasTickerCard from '../components/CanvasTickerCard'
import ComparisonTable from '../components/ComparisonTable'
import { useResearchChat } from '../context/ResearchChatContext'
import { suggestionsFor } from './suggestions'
import './ResearchChat.css'

// The chat agent's replies only ever use **bold** and `code` - split on those
// rather than pulling in a markdown library for two inline styles.
function renderText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
    return part
  })
}

export default function ResearchChat() {
  const { messages, tickers, sending, error, sendMessage } = useResearchChat()
  const [input, setInput] = useState('')
  const [selected, setSelected] = useState([])

  function handleSubmit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text) return
    setInput('')
    sendMessage(text)
  }

  function toggleSelect(ticker) {
    setSelected((prev) => (prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]))
  }

  const canvasCards = Object.values(tickers).sort((a, b) => b.seq - a.seq)
  const suggestions = suggestionsFor(canvasCards[0])
  const comparedTickers = selected.map((t) => tickers[t]).filter(Boolean)

  return (
    <div className="page research-chat">
      <span className="eyebrow">Research Chat</span>
      <h2>Ask about a stock</h2>

      {comparedTickers.length >= 2 && (
        <ComparisonTable tickers={comparedTickers} onClear={() => setSelected([])} />
      )}

      <div className="research-chat__layout">
        <div className="research-chat__main">
          <div className="research-chat__transcript">
            {messages.length === 0 && (
              <p className="research-chat__empty">
                Ask about a price, market cap, P/E ratio, day change, price history, or your watchlist. Every
                ticker you mention builds up a live card on the right.
              </p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`research-chat__row research-chat__row--${m.role}`}>
                <span className="research-chat__role">{m.role === 'user' ? 'You' : 'Agent'}</span>
                <div className="research-chat__content">
                  {m.calls?.length > 0 && (
                    <div className="research-chat__calls">
                      {m.calls.map((c, i) => (
                        <ToolCallPill key={i} toolName={c.toolName} done={c.done} />
                      ))}
                    </div>
                  )}
                  {m.text && <p className="research-chat__text">{renderText(m.text)}</p>}
                  {m.error && (
                    <p className="research-chat__message-error">Couldn't finish that: {m.error}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {error && <div className="error-banner research-chat__error">{error}</div>}

          {suggestions.length > 0 && (
            <div className="research-chat__suggestions">
              {suggestions.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  className="research-chat__suggestion"
                  disabled={sending}
                  onClick={() => sendMessage(s.text)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          <form className="research-chat__input" onSubmit={handleSubmit}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about a ticker…"
              disabled={sending}
            />
            <button type="submit" disabled={sending || !input.trim()}>
              {sending ? 'Sending…' : 'Send'}
            </button>
          </form>
        </div>

        <aside className="research-chat__canvas">
          <span className="eyebrow">Research canvas</span>
          {canvasCards.length === 0 ? (
            <p className="research-chat__empty">Tickers you ask about will collect here.</p>
          ) : (
            <div className="research-chat__canvas-grid">
              {canvasCards.map((data) => (
                <CanvasTickerCard
                  key={data.ticker}
                  data={data}
                  selected={selected.includes(data.ticker)}
                  onToggleSelect={toggleSelect}
                />
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
