import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/** Gates a route behind a logged-in user, redirecting to /login otherwise. */
export default function RequireAuth({ children }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return null
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return children
}
