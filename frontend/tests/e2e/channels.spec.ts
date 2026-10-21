import { test, expect } from '@playwright/test'
import { createDevUser } from './helpers/dev-fixtures'
import { gotoRetrying, loginViaUi, uniqueEmail, TEST_PASSWORD } from './helpers/auth'
import { extractLink, waitForEmail } from './helpers/mailpit'
import { setChaosMode, getWebhookLog } from './helpers/chaos'

test.describe('notification channels', () => {
  test('add email channel, verify via Mailpit, add webhook channel, verify, route to a monitor, see an alert delivered', async ({
    page,
  }) => {
    const email = uniqueEmail('pw-channels')
    await createDevUser(email, TEST_PASSWORD)
    await loginViaUi(page, email, TEST_PASSWORD)

    const alertEmail = uniqueEmail('pw-channels-alerts')
    const webhookPath = `/webhook`
    await setChaosMode(webhookPath, 'up', { status_code: 200 })

    // --- email channel: add, verify via the Mailpit link ---
    await gotoRetrying(page, '/settings/channels')
    await page.getByRole('button', { name: 'Add channel' }).click()
    await page.getByLabel('Name').fill('Ops inbox')
    await page.getByLabel('Email address').fill(alertEmail)
    await page.getByRole('button', { name: 'Add channel' }).nth(1).click()
    await expect(page.getByText('Ops inbox')).toBeVisible()

    await page.getByRole('button', { name: 'Verify' }).first().click()
    await expect(page.getByText('Verification link sent.')).toBeVisible()

    const verifyMessage = await test.step('waitForEmail (channel verify)', () =>
      waitForEmail(alertEmail, 'Verify your Cronos account'),
    )
    const verifyUrl = new URL(extractLink(verifyMessage.Snippet))
    await gotoRetrying(page, verifyUrl.pathname + verifyUrl.search)
    await page.getByRole('button', { name: 'Verify channel' }).click()
    await expect(page.getByText(/verified/i)).toBeVisible()

    await gotoRetrying(page, '/settings/channels')
    await expect(page.getByText('Verified').first()).toBeVisible()

    // --- webhook channel pointed at chaos: add, verify synchronously ---
    await page.getByRole('button', { name: 'Add channel' }).click()
    await page.getByLabel('Name').fill('Ops webhook')
    await page.getByLabel('Kind').selectOption('webhook')
    await page.getByLabel('Webhook URL').fill('http://chaos:8000/webhook')
    await page.getByRole('button', { name: 'Add channel' }).nth(1).click()
    await expect(page.getByText('Ops webhook')).toBeVisible()

    const webhookRow = page.getByText('Ops webhook').locator('..').locator('..')
    await webhookRow.getByRole('button', { name: 'Verify' }).click()
    await expect(webhookRow.getByText('Verified')).toBeVisible({ timeout: 10000 })

    // --- route both channels to a fresh monitor, drive it down, expect a delivered alert ---
    const chaosPath = `/e2e-channels-${Date.now()}`
    await setChaosMode(chaosPath, 'down')

    await gotoRetrying(page, '/monitors/new')
    await page.getByLabel('Name').fill('Channels E2E target')
    await page.getByLabel('URL').fill(`http://chaos:8000${chaosPath}`)
    await page.getByRole('button', { name: 'Advanced' }).click()
    await page.getByLabel('Confirm threshold').fill('1')
    // Both channels are checked by default here only if they happen to be is_default -- force
    // both on explicitly so this test doesn't depend on that unrelated setting.
    await page.getByLabel('Ops inbox').check()
    await page.getByLabel('Ops webhook').check()
    await page.getByRole('button', { name: 'Create monitor' }).click()
    await page.waitForURL('/monitors')

    await page.getByRole('button', { name: 'Check now' }).click()

    await test.step('waitForEmail (DOWN alert)', () =>
      waitForEmail(alertEmail, 'DOWN'),
    )

    await expect(async () => {
      const log = await getWebhookLog()
      expect(log.some((row) => row.event === 'opened' && row.verified === true)).toBe(true)
    }).toPass({ timeout: 20000, intervals: [1000, 2000, 3000] })

    // --- delivery log drawer shows both as sent ---
    await gotoRetrying(page, '/settings/channels')
    const inboxRow = page.getByText('Ops inbox').locator('..').locator('..')
    await inboxRow.getByRole('button', { name: 'Deliveries' }).click()
    await expect(page.getByText('Delivery log.')).toBeVisible()
    await expect(page.getByText('sent', { exact: true })).toBeVisible({ timeout: 15000 })
  })

  test('a non-2xx webhook verify response shows a friendly inline error', async ({ page }) => {
    const email = uniqueEmail('pw-channels')
    await createDevUser(email, TEST_PASSWORD)
    await loginViaUi(page, email, TEST_PASSWORD)
    await setChaosMode('/webhook', 'up', { status_code: 500 })

    await gotoRetrying(page, '/settings/channels')
    await page.getByRole('button', { name: 'Add channel' }).click()
    await page.getByLabel('Name').fill('Flaky webhook')
    await page.getByLabel('Kind').selectOption('webhook')
    await page.getByLabel('Webhook URL').fill('http://chaos:8000/webhook')
    await page.getByRole('button', { name: 'Add channel' }).nth(1).click()

    await page.getByRole('button', { name: 'Verify' }).click()
    await expect(page.getByText(/couldn.t verify the webhook/i)).toBeVisible()
  })
})
