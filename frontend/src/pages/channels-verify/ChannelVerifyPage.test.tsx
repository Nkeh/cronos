import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ChannelVerifyPage } from './ChannelVerifyPage'

function renderPage(search: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/channels/verify${search}`]}>
        <ChannelVerifyPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ChannelVerifyPage', () => {
  it('disables the verify button when no token is present in the URL', () => {
    renderPage('')
    const button = screen.getByRole('button', { name: /verify channel/i }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it('enables the verify button once a token is present', () => {
    renderPage('?token=abc123')
    const button = screen.getByRole('button', { name: /verify channel/i }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
  })

  it('never submits on mount -- only an explicit click triggers verification (mail-scanner rule)', () => {
    renderPage('?token=abc123')
    // Still on the "click to verify" state, not the success state -- nothing fired automatically.
    expect(screen.getByRole('button', { name: /verify channel/i })).toBeTruthy()
    expect(screen.queryByText(/go to channels/i)).toBeNull()
  })
})
