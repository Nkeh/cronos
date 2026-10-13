import { afterEach, describe, expect, it } from 'vitest'
import {
  applyThemeAttribute,
  readStoredTheme,
  THEME_STORAGE_KEY,
  writeStoredTheme,
} from './theme-storage'

describe('theme-storage', () => {
  afterEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to "system" when nothing is stored', () => {
    expect(readStoredTheme()).toBe('system')
  })

  it('reads back an explicit "light" or "dark" choice', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    expect(readStoredTheme()).toBe('dark')
  })

  it('treats a corrupted stored value as "system"', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'neon')
    expect(readStoredTheme()).toBe('system')
  })

  it('writeStoredTheme removes the key for "system" (no flash relies on its absence)', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    writeStoredTheme('system')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  })

  it('writeStoredTheme persists an explicit choice', () => {
    writeStoredTheme('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })

  it('applyThemeAttribute sets data-theme for an explicit choice', () => {
    applyThemeAttribute('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('applyThemeAttribute removes data-theme for "system"', () => {
    document.documentElement.setAttribute('data-theme', 'dark')
    applyThemeAttribute('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})
