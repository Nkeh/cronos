import { Navigate, Outlet } from 'react-router'
import { useAuthMe } from '../../features/auth/hooks'

/** Authenticated users visiting /login, /signup, etc. are redirected to the dashboard. */
export function AuthLayout() {
  const { data, isSuccess } = useAuthMe()
  if (isSuccess && data) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
