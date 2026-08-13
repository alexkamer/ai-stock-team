import { createContext, useContext, useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api/client'

const AuthContext = createContext(null)

/**
 * The current logged-in user, mirrored from the backend session cookie -
 * unlike WatchlistContext there's nothing to persist client-side, the
 * httponly cookie *is* the persistence. On mount this just asks the
 * backend who's logged in via GET /api/auth/me.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    getJSON('/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false))
  }, [])

  async function signup(email, password) {
    const account = await postJSON('/auth/signup', { email, password })
    setUser(account)
    return account
  }

  async function login(email, password) {
    const account = await postJSON('/auth/login', { email, password })
    setUser(account)
    return account
  }

  async function logout() {
    await postJSON('/auth/logout').catch(() => {})
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, signup, login, logout }}>{children}</AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
