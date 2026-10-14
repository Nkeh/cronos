import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { gotoRetrying } from './helpers/auth'
import { AUTH_STATE_PATH, FIXTURES } from './helpers/shared-user'

const unauthPages = ['/login', '/signup', '/verify', '/forgot', '/reset']
const themes = ['light', 'dark'] as const

async function expectNoSeriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze()
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  )
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
}

for (const path of unauthPages) {
  for (const theme of themes) {
    test(`axe: ${path} (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await gotoRetrying(page, path)
      await expectNoSeriousViolations(page)
    })
  }
}

test.describe('authenticated pages', () => {
  test.use({ storageState: AUTH_STATE_PATH })

  for (const theme of themes) {
    test(`axe: / overview (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await gotoRetrying(page, '/')
      await expectNoSeriousViolations(page)
    })

    test(`axe: /monitors empty (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await gotoRetrying(page, '/monitors')
      await expectNoSeriousViolations(page)
    })

    test(`axe: /monitors/new (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await gotoRetrying(page, '/monitors/new')
      await expectNoSeriousViolations(page)
    })
  }
})

test.describe('authenticated pages (seeded monitors)', () => {
  test.use({ storageState: FIXTURES.seeded.statePath })

  for (const theme of themes) {
    test(`axe: /monitors seeded (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme })
      await gotoRetrying(page, '/monitors')
      await expectNoSeriousViolations(page)
    })

    test(`axe: /monitors/:id/edit (${theme})`, async ({ page }) => {
      // Also forces transition-duration to ~0 (see index.css's prefers-reduced-motion block),
      // which closes the race this test used to lose: fields fade in via a CSS color transition
      // once GET /monitors/:id resolves, and axe measured mid-transition blended colors as a
      // false "insufficient contrast" violation on a host under heavy CPU contention.
      await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
      await gotoRetrying(page, '/monitors')
      await page.getByRole('link', { name: 'Edit monitor' }).first().click()
      await page.waitForURL(/\/monitors\/.+\/edit/)
      await expect(page.locator('#name')).not.toHaveValue('')
      await expectNoSeriousViolations(page)
    })
  }
})
