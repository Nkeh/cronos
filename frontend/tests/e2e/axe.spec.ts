import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { AUTH_STATE_PATH } from './helpers/shared-user'

const unauthPages = ['/login', '/signup', '/verify', '/forgot', '/reset']
const themes = ['light', 'dark'] as const

for (const path of unauthPages) {
  for (const theme of themes) {
    test(`axe: ${path} (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await page.goto(path)
      const results = await new AxeBuilder({ page }).analyze()
      const serious = results.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      )
      expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
    })
  }
}

test.describe('authenticated pages', () => {
  test.use({ storageState: AUTH_STATE_PATH })

  for (const theme of themes) {
    test(`axe: / overview (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await page.goto('/')
      const results = await new AxeBuilder({ page }).analyze()
      const serious = results.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      )
      expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
    })
  }
})
