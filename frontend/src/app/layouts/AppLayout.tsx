import { Navigate, useLocation } from 'react-router'
import { useAuthMe } from '../../features/auth/hooks'
import { Navbar } from '../shell/Navbar/Navbar'
import { UnverifiedBanner } from '../shell/UnverifiedBanner'
import { Skeleton } from '../../components/ui/Skeleton'
import { PageTransition } from '../../components/motion/PageTransition'

export function AppLayout() {
  const location = useLocation()
  const { data, isLoading, isError } = useAuthMe()

  if (isLoading) {
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-16">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (isError || !data) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  return (
    <div className="min-h-screen">
      <div className="ambient-bg" />
      {!data.email_verified && <UnverifiedBanner />}
      <main className="mx-auto max-w-5xl px-6 pb-[calc(96px+2rem)] pt-10">
        <PageTransition />
      </main>
      <Navbar />
    </div>
  )
}
