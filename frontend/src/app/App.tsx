import { useEffect, useState } from 'react'
import { checkApiStatus, type ApiStatus } from '../lib/api/client'

export function App() {
  const [status, setStatus] = useState<ApiStatus | 'checking'>('checking')

  useEffect(() => {
    const controller = new AbortController()
    checkApiStatus(controller.signal).then(setStatus)
    return () => controller.abort()
  }, [])

  const dotClass =
    status === 'up' ? 'bg-emerald-400' : status === 'down' ? 'bg-red-500' : 'bg-slate-500'
  const label = status === 'checking' ? 'Checking API…' : status === 'up' ? 'API up' : 'API down'

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-slate-950 px-6 text-center text-slate-100">
      <p className="text-sm uppercase tracking-widest text-slate-400">Uptime &amp; cron monitoring</p>
      <h1 className="text-6xl font-semibold tracking-tight">Cronos.</h1>
      <span
        data-testid="api-status-pill"
        className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900 px-4 py-1.5 text-sm"
      >
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        {label}
      </span>
    </main>
  )
}
