export type ThemeMode = 'system' | 'light' | 'dark'

export const THEME_STORAGE_KEY = 'cronos-theme'

export function readStoredTheme(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
    return 'system'
  } catch {
    return 'system'
  }
}

export function writeStoredTheme(mode: ThemeMode) {
  try {
    if (mode === 'system') {
      localStorage.removeItem(THEME_STORAGE_KEY)
    } else {
      localStorage.setItem(THEME_STORAGE_KEY, mode)
    }
  } catch {
    /* storage unavailable — theme just won't persist across reloads */
  }
}

export function applyThemeAttribute(mode: ThemeMode) {
  if (mode === 'system') {
    document.documentElement.removeAttribute('data-theme')
  } else {
    document.documentElement.setAttribute('data-theme', mode)
  }
}

export function prefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}
