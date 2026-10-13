import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider, useTheme } from './ThemeProvider'
import { THEME_STORAGE_KEY } from './theme-storage'

class FakeMediaQueryList {
  matches: boolean
  listeners = new Set<(event: { matches: boolean }) => void>()

  constructor(matches: boolean) {
    this.matches = matches
  }

  addEventListener(_: string, listener: (event: { matches: boolean }) => void) {
    this.listeners.add(listener)
  }

  removeEventListener(_: string, listener: (event: { matches: boolean }) => void) {
    this.listeners.delete(listener)
  }

  emit(matches: boolean) {
    this.matches = matches
    this.listeners.forEach((listener) => listener({ matches }))
  }
}

function Probe() {
  const { theme, resolvedTheme } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
    </div>
  )
}

describe('ThemeProvider', () => {
  let mql: FakeMediaQueryList

  beforeEach(() => {
    mql = new FakeMediaQueryList(false)
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockImplementation(() => mql),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('resolves to "system" + the current OS scheme when nothing is stored', () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('system')
    expect(screen.getByTestId('resolved').textContent).toBe('light')
  })

  it('follows an emulated OS theme change live while mode is "system"', () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('resolved').textContent).toBe('light')

    act(() => {
      mql.emit(true)
    })

    expect(screen.getByTestId('resolved').textContent).toBe('dark')
  })

  it('an explicit choice persists to localStorage and ignores further OS changes', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('resolved').textContent).toBe('light')

    act(() => {
      mql.emit(true)
    })

    // Explicit "light" ignores the OS switching to dark.
    expect(screen.getByTestId('resolved').textContent).toBe('light')
  })
})
