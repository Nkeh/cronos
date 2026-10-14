import { test, expect } from '@playwright/test'
import { extractLink, waitForEmail } from './helpers/mailpit'
import { gotoRetrying, signupVerifyLogin, TEST_PASSWORD, uniqueEmail } from './helpers/auth'
import { SHARED_EMAIL } from './helpers/shared-user'

test('signup -> verify -> login -> navbar -> logout', async ({ page }) => {
  const email = uniqueEmail('pw-auth')

  await signupVerifyLogin(page, email)
  await expect(page.getByRole('heading', { name: 'Overview.' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')

  await page.getByRole('link', { name: 'Monitors' }).click()
  await expect(page).toHaveURL('/monitors')
  await expect(page.getByRole('heading', { name: 'Monitors.' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Monitors' })).toHaveAttribute('aria-current', 'page')

  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await expect(page).toHaveURL('/login')

  // the guarded route redirects back to login once the session is gone
  await gotoRetrying(page, '/monitors')
  await expect(page).toHaveURL(/\/login\?next=/)
})

test('an unverified account sees the resend banner', async ({ page }) => {
  const email = uniqueEmail('pw-unverified')
  await gotoRetrying(page, '/signup')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(TEST_PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await waitForEmail(email, 'Verify your Cronos account')

  // Log in without clicking the verify link first.
  await gotoRetrying(page, '/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(TEST_PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/')

  await expect(page.getByText('Verify your email to create monitors and heartbeats.')).toBeVisible()
})

test('invalid credentials show a form-level error', async ({ page }) => {
  // Reuses the shared account (no fresh signup) — signup is rate-limited to 5/hour per IP, and
  // every request from this container shares one IP via network_mode: service:caddy.
  await gotoRetrying(page, '/login')
  await page.getByLabel('Email').fill(SHARED_EMAIL)
  await page.getByLabel('Password').fill('totally-wrong')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText('That email or password is incorrect.')).toBeVisible()
})

test('forgot -> reset -> login with the new password', async ({ page }) => {
  const email = uniqueEmail('pw-reset')
  await signupVerifyLogin(page, email)
  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()

  await gotoRetrying(page, '/forgot')
  await page.getByLabel('Email').fill(email)
  await page.getByRole('button', { name: 'Send reset link' }).click()
  await expect(page.getByText(/reset link has been sent/i)).toBeVisible()

  const message = await waitForEmail(email, 'Reset your Cronos password')
  const resetUrl = new URL(extractLink(message.Snippet))
  const newPassword = 'AnotherStrongPass9'

  await gotoRetrying(page, resetUrl.pathname + resetUrl.search)
  await page.getByLabel('New password').fill(newPassword)
  await page.getByRole('button', { name: 'Reset password' }).click()
  await expect(page).toHaveURL('/login')

  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(newPassword)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL('/')
})
