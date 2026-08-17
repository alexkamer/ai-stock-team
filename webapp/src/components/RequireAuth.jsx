import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/** Gates a route behind a logged-in user, redirecting to /login otherwise.
 * A no-op when the backend has AUTH_REQUIRED=false (the fork-and-run default). */
export default function RequireAuth({ children }) {
  const { user, authRequired, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return null
  if (!authRequired) return children
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return children
}
