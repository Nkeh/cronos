import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { DeliveryLogDrawer } from './DeliveryLogDrawer'
import type { Delivery } from '../../lib/api/types'

const DELIVERY: Delivery = {
  id: 'n1',
  event: 'opened',
  status: 'sent',
  attempts: 2,
  created_at: new Date(Date.now() - 60_000).toISOString(),
  sent_at: new Date().toISOString(),
  last_error: null,
  recent_attempts: [
    { id: 1, attempted_at: new Date(Date.now() - 120_000).toISOString(), outcome: 'retry', status_code: 500, error: 'boom', duration_ms: 12 },
    { id: 2, attempted_at: new Date().toISOString(), outcome: 'sent', status_code: 200, error: null, duration_ms: 8 },
  ],
}

vi.mock('./hooks', () => ({
  useChannelDeliveries: vi.fn(() => ({
    data: { pages: [{ items: [DELIVERY], next_cursor: null }] },
    isLoading: false,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  })),
}))

function renderDrawer() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <DeliveryLogDrawer channelId="c1" open onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

describe('DeliveryLogDrawer', () => {
  it('renders the delivery status and event', () => {
    renderDrawer()
    expect(screen.getByText('sent')).toBeTruthy()
    expect(screen.getByText('opened')).toBeTruthy()
  })

  it('renders each attempt with its outcome and status code', () => {
    renderDrawer()
    expect(screen.getByText(/retry \(500\)/)).toBeTruthy()
    expect(screen.getByText(/sent \(200\)/)).toBeTruthy()
  })
})
