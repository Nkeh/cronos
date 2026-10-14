import type { Page } from '@playwright/test'
import { extractLink, waitForEmail } from './mailpit'

export const TEST_PASSWORD = 'CorrectHorseBattery9'

const GOTO_TIMEOUT_MS = 20000
const GOTO_OPTS = { timeout: GOTO_TIMEOUT_MS, waitUntil: 'domcontentloaded' as const }

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

/** This sandbox's dev Vite server occasionally takes >20s on a single navigation (cold
 * transform, polling-mode file watcher competing for CPU — see docs/progress for the
 * measurements) even with no other load, so one bounded retry absorbs that without masking a
 * real hang: two slow attempts still fail loudly, just later. */
export async function gotoRetrying(page: Page, url: string, attempts = 2): Promise<void> {
  let lastError: unknown
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      await page.goto(url, GOTO_OPTS)
      return
    } catch (err) {
      lastError = err
    }
  }
  throw lastError
}

/** Signs up a fresh user, verifies via the Mailpit link, and logs in. Leaves the page on "/".
 * Only auth.spec.ts's own signup/verify/forgot/reset tests use this — everything else gets its
 * user from the dev-only fixture endpoints (helpers/dev-fixtures.ts) plus loginViaUi below. */
export async function signupVerifyLogin(page: Page, email: string, password = TEST_PASSWORD) {
  await gotoRetrying(page, '/signup')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()

  const message = await waitForEmail(email, 'Verify your Cronos account')
  const verifyUrl = new URL(extractLink(message.Snippet))
  await gotoRetrying(page, verifyUrl.pathname + verifyUrl.search)
  await page.getByRole('button', { name: 'Verify my email' }).click()

  await gotoRetrying(page, '/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/', { timeout: GOTO_TIMEOUT_MS })
}

/** Logs in an already-created (dev-fixture) user through the real login form — fast, no
 * Mailpit round-trip. Works for unverified users too (login doesn't require verification). */
export async function loginViaUi(page: Page, email: string, password = TEST_PASSWORD) {
  await gotoRetrying(page, '/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/', { timeout: GOTO_TIMEOUT_MS })
}
