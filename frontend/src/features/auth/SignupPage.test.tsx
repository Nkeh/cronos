import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { SignupPage } from './SignupPage'

function renderSignup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SignupPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SignupPage', () => {
  it('shows the password policy hint', () => {
    renderSignup()
    expect(screen.getByText(/at least 8 characters/i)).toBeTruthy()
  })

  it('enforces an 8-character minimum on the password field', () => {
    renderSignup()
    const password = screen.getByLabelText('Password') as HTMLInputElement
    expect(password.minLength).toBe(8)
  })

  it('updates the password field as the user types', () => {
    renderSignup()
    const password = screen.getByLabelText('Password') as HTMLInputElement
    fireEvent.change(password, { target: { value: 'longenoughpassword' } })
    expect(password.value).toBe('longenoughpassword')
  })

  it('requires both email and password before submission', () => {
    renderSignup()
    const email = screen.getByLabelText('Email') as HTMLInputElement
    const password = screen.getByLabelText('Password') as HTMLInputElement
    expect(email.required).toBe(true)
    expect(password.required).toBe(true)
  })
})
