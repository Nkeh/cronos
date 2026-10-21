import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { AddChannelDialog } from './AddChannelDialog'
import { Button } from '../../components/ui/Button'

function renderDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AddChannelDialog trigger={<Button>Add channel</Button>} />
    </QueryClientProvider>,
  )
}

describe('AddChannelDialog', () => {
  it('defaults to the email kind, with an email-typed required address field', () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }))
    const address = screen.getByLabelText('Email address') as HTMLInputElement
    expect(address.type).toBe('email')
    expect(address.required).toBe(true)
  })

  it('switching to webhook swaps the address field for a required url-typed field', () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }))
    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'webhook' } })

    expect(screen.queryByLabelText('Email address')).toBeNull()
    const url = screen.getByLabelText('Webhook URL') as HTMLInputElement
    expect(url.type).toBe('url')
    expect(url.required).toBe(true)
  })

  it('the name field is capped at 60 characters, matching the backend check constraint', () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }))
    const name = screen.getByLabelText('Name') as HTMLInputElement
    expect(name.maxLength).toBe(60)
  })

  it('"route by default" starts unchecked', () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }))
    const checkbox = screen.getByLabelText(/route every new monitor here by default/i) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
  })
})
