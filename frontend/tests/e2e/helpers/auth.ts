import type { Page } from '@playwright/test'
import { extractLink, waitForEmail } from './mailpit'

export const TEST_PASSWORD = 'CorrectHorseBattery9'

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

/** Signs up a fresh user, verifies via the Mailpit link, and logs in. Leaves the page on "/". */
export async function signupVerifyLogin(page: Page, email: string, password = TEST_PASSWORD) {
  await page.goto('/signup')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()

  const message = await waitForEmail(email, 'Verify your Cronos account')
  const verifyUrl = new URL(extractLink(message.Snippet))
  await page.goto(verifyUrl.pathname + verifyUrl.search)
  await page.getByRole('button', { name: 'Verify my email' }).click()

  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/')
}
