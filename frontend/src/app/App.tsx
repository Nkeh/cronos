import { useEffect } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { ThemeProvider } from '../features/theme/ThemeProvider'
import { ToastProvider } from '../features/toast/ToastProvider'
import { queryClient } from '../lib/queryClient'
import { fetchCsrfToken } from '../lib/api/auth'
import { AppRouter } from './router'

export function App() {
  useEffect(() => {
    fetchCsrfToken()
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionConfig reducedMotion="user">
          <ToastProvider>
            <AppRouter />
          </ToastProvider>
        </MotionConfig>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
