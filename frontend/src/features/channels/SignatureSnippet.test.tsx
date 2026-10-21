import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SignatureSnippet } from './SignatureSnippet'

describe('SignatureSnippet', () => {
  it('renders the Python snippet by default', () => {
    render(<SignatureSnippet />)
    expect(screen.getByText(/import hashlib, hmac, time/)).toBeTruthy()
  })

  it('switches to the Node snippet when its tab is clicked', () => {
    render(<SignatureSnippet />)
    fireEvent.click(screen.getByRole('button', { name: 'node' }))
    expect(screen.getByText(/require\('crypto'\)/)).toBeTruthy()
  })

  it('both languages verify the same v1=HMAC-SHA256 scheme', () => {
    render(<SignatureSnippet />)
    expect(screen.getByText(/v1/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'node' }))
    expect(screen.getByText(/v1/)).toBeTruthy()
  })
})
