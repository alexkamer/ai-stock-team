import { createContext, useContext, useEffect, useState } from 'react'

const STORAGE_KEY = 'watchlist'
const DEFAULT_WATCHLIST = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN']

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const WatchlistContext = createContext(null)

/**
 * The user's watchlist, persisted to localStorage - there's no backend
 * storage or auth in this app yet, so the browser is the only place a
 * per-user list can live. Falls back to a fixed default list on first
 * visit. Drives both the Dashboard's watchlist card and the chat agent's
 * system-prompt context (passed along on each /chat request).
 */
export function WatchlistProvider({ children }) {
  const [tickers, setTickers] = useState(() => loadPersisted() ?? DEFAULT_WATCHLIST)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tickers))
    } catch {
      // localStorage unavailable (private browsing, quota) - watchlist just won't persist
    }
  }, [tickers])

  function addTicker(ticker) {
    const symbol = ticker.trim().toUpperCase()
    if (!symbol || tickers.includes(symbol)) return
    setTickers((prev) => [...prev, symbol])
  }

  function removeTicker(ticker) {
    setTickers((prev) => prev.filter((t) => t !== ticker))
  }

  return (
    <WatchlistContext.Provider value={{ tickers, addTicker, removeTicker }}>{children}</WatchlistContext.Provider>
  )
}

export function useWatchlist() {
  const ctx = useContext(WatchlistContext)
  if (!ctx) throw new Error('useWatchlist must be used within a WatchlistProvider')
  return ctx
}
