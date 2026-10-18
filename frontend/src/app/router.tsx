import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AuthLayout } from './layouts/AuthLayout'
import { AppLayout } from './layouts/AppLayout'
import { PlaceholderPage } from './shell/PlaceholderPage'
import { OverviewPage } from '../pages/overview/OverviewPage'
import { Skeleton } from '../components/ui/Skeleton'

const LoginPage = lazy(() => import('../features/auth/LoginPage').then((m) => ({ default: m.LoginPage })))
const SignupPage = lazy(() =>
  import('../features/auth/SignupPage').then((m) => ({ default: m.SignupPage })),
)
const VerifyPage = lazy(() =>
  import('../features/auth/VerifyPage').then((m) => ({ default: m.VerifyPage })),
)
const ForgotPage = lazy(() =>
  import('../features/auth/ForgotPage').then((m) => ({ default: m.ForgotPage })),
)
const ResetPage = lazy(() =>
  import('../features/auth/ResetPage').then((m) => ({ default: m.ResetPage })),
)

const MonitorsListPage = lazy(() =>
  import('../features/monitors/MonitorsListPage').then((m) => ({ default: m.MonitorsListPage })),
)
const MonitorFormPage = lazy(() =>
  import('../features/monitors/MonitorFormPage').then((m) => ({ default: m.MonitorFormPage })),
)

const IncidentsListPage = lazy(() =>
  import('../features/incidents/IncidentsListPage').then((m) => ({
    default: m.IncidentsListPage,
  })),
)
const IncidentDetailPage = lazy(() =>
  import('../features/incidents/IncidentDetailPage').then((m) => ({
    default: m.IncidentDetailPage,
  })),
)

// Statically resolved by Vite (`import.meta.env.DEV` is a build-time constant), so the ternary's
// false branch — including the dynamic import() itself — is dead-code-eliminated in production.
const DesignPreviewPage = import.meta.env.DEV
  ? lazy(() =>
      import('../pages/dev-design/DesignPreviewPage').then((m) => ({
        default: m.DesignPreviewPage,
      })),
    )
  : null

function RouteFallback() {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  )
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route element={<AuthLayout />}>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            <Route path="/forgot" element={<ForgotPage />} />
            <Route path="/reset" element={<ResetPage />} />
          </Route>

          <Route element={<AppLayout />}>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/monitors" element={<MonitorsListPage />} />
            <Route path="/monitors/new" element={<MonitorFormPage />} />
            <Route path="/monitors/:id/edit" element={<MonitorFormPage />} />
            <Route
              path="/heartbeats"
              element={
                <PlaceholderPage eyebrow="Dead man's switches" title="Heartbeats." day={10} />
              }
            />
            <Route path="/incidents" element={<IncidentsListPage />} />
            <Route path="/incidents/:id" element={<IncidentDetailPage />} />
            <Route
              path="/status-pages"
              element={
                <PlaceholderPage eyebrow="What the world sees" title="Status pages." day={11} />
              }
            />
          </Route>

          {import.meta.env.DEV && DesignPreviewPage && (
            <Route path="/dev/design" element={<DesignPreviewPage />} />
          )}

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
