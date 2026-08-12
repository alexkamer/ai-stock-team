import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { getJSON, streamSSE } from '../api/client'
import { applyBaseline, applyToolResult } from '../pages/researchCanvas'
import { useWatchlist } from './WatchlistContext'

const ResearchChatContext = createContext(null)

const STORAGE_KEY = 'research-chat-state'

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function savePersisted(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // localStorage unavailable (private browsing, quota) - chat just won't survive a refresh
  }
}

let nextId = 0

/**
 * Owns the chat transcript, research canvas, and session id at the App
 * level (mounted once, above <Routes>) instead of inside the ResearchChat
 * page - so navigating to a ticker's detail page and back leaves the
 * conversation intact. Also persists to localStorage so a hard refresh or
 * reopened tab restores it too - the one gap left is the backend's session
 * history, which is in-memory only (Phase 1 v1 tradeoff) and clears on a
 * server restart; resending after that just starts the agent with no prior
 * context under the same session_id, which is a quiet degradation, not an
 * error.
 */
export function ResearchChatProvider({ children }) {
  const { tickers: watchlistTickers } = useWatchlist()
  const persisted = useRef(loadPersisted()).current
  const [messages, setMessages] = useState(() => {
    if (persisted?.messages?.length) nextId = Math.max(nextId, ...persisted.messages.map((m) => m.id + 1))
    return persisted?.messages ?? []
  })
  const [tickers, setTickers] = useState(persisted?.tickers ?? {})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const sessionIdRef = useRef(persisted?.sessionId ?? null)
  const baselinesFetchedRef = useRef(new Set(Object.keys(persisted?.tickers ?? {})))

  useEffect(() => {
    savePersisted({ messages, tickers, sessionId: sessionIdRef.current })
  }, [messages, tickers])

  function ensureBaseline(ticker) {
    if (baselinesFetchedRef.current.has(ticker)) return
    baselinesFetchedRef.current.add(ticker)
    getJSON(`/watchlist?symbols=${ticker}`)
      .then(([quote]) => {
        if (quote) setTickers((prev) => applyBaseline(prev, ticker, quote))
      })
      .catch(() => {})
  }

  async function sendMessage(text) {
    if (!text || sending) return

    const userMessage = { id: nextId++, role: 'user', text }
    const assistantMessage = { id: nextId++, role: 'assistant', text: '', calls: [] }
    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setSending(true)
    setError(null)

    // Tracks each in-flight tool call's args by name, so the matching
    // tool_result (which carries no args of its own) can be folded into the
    // canvas - kept outside React state since it's write-once scratch data
    // for this one request, not something the UI renders directly.
    const pendingArgs = []

    try {
      await streamSSE('/chat', {
        method: 'POST',
        body: { message: text, session_id: sessionIdRef.current, watchlist: watchlistTickers },
        onEvent: (eventName, data) => {
          if (eventName === 'session') {
            sessionIdRef.current = data.session_id
          } else if (eventName === 'text') {
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantMessage.id ? { ...m, text: m.text + data.delta } : m))
            )
          } else if (eventName === 'tool_call') {
            pendingArgs.push({ toolName: data.tool_name, args: data.args, matched: false })
            if (data.args?.ticker) ensureBaseline(data.args.ticker.toUpperCase())
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, calls: [...m.calls, { toolName: data.tool_name, args: data.args, done: false }] }
                  : m
              )
            )
          } else if (eventName === 'tool_result') {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== assistantMessage.id) return m
                const index = m.calls.findIndex((c) => c.toolName === data.tool_name && !c.done)
                if (index === -1) return m
                const calls = [...m.calls]
                calls[index] = { ...calls[index], done: true, content: data.content }
                return { ...m, calls }
              })
            )
            const call = pendingArgs.find((c) => c.toolName === data.tool_name && !c.matched)
            if (call) call.matched = true
            setTickers((prev) => applyToolResult(prev, data.tool_name, call?.args, data.content))
            if (data.tool_name === 'get_watchlist_prices' && data.content && typeof data.content === 'object') {
              Object.keys(data.content).forEach((t) => ensureBaseline(t.toUpperCase()))
            }
          } else if (eventName === 'error') {
            // A tool failure (e.g. an unrecognized ticker) - shown inline on
            // this message rather than a global banner, since it's specific
            // to the question just asked, not the connection as a whole.
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantMessage.id ? { ...m, error: data.detail } : m))
            )
          }
        },
      })
    } catch (e) {
      // A connection-level failure (request never completed), not a tool
      // error - shown as a global banner since there's no per-message
      // response to attach it to.
      setError(e.message || 'Lost connection to the chat service.')
    } finally {
      setSending(false)
    }
  }

  return (
    <ResearchChatContext.Provider value={{ messages, tickers, sending, error, sendMessage }}>
      {children}
    </ResearchChatContext.Provider>
  )
}

export function useResearchChat() {
  const ctx = useContext(ResearchChatContext)
  if (!ctx) throw new Error('useResearchChat must be used within a ResearchChatProvider')
  return ctx
}
