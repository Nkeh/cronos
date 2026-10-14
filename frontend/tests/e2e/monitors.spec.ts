import { test, expect } from '@playwright/test'
import { createDevUser, seedMonitors } from './helpers/dev-fixtures'
import { gotoRetrying, loginViaUi, uniqueEmail, TEST_PASSWORD } from './helpers/auth'
import { FIXTURES } from './helpers/shared-user'

test.describe('monitor CRUD flow', () => {
  test('create -> edit (pre-populated) -> pause -> resume -> check now -> delete', async ({
    page,
  }) => {
    const email = uniqueEmail('pw-monitors')
    await createDevUser(email, TEST_PASSWORD)
    await loginViaUi(page, email, TEST_PASSWORD)

    await gotoRetrying(page, '/monitors/new')
    await page.getByLabel('Name').fill('Example monitor')
    await page.getByLabel('URL').fill('http://chaos:8000/health')
    await page.getByRole('button', { name: 'Create monitor' }).click()
    await page.waitForURL('/monitors')
    await expect(page.getByText('Example monitor')).toBeVisible()

    await page.getByRole('link', { name: 'Edit monitor' }).click()
    await expect(page.getByLabel('Name')).toHaveValue('Example monitor')
    await expect(page.getByLabel('URL')).toHaveValue('http://chaos:8000/health')
    await expect(page.getByLabel('Method')).toHaveValue('GET')
    await expect(page.getByLabel('Expected status')).toHaveValue('2xx')

    await page.getByLabel('Name').fill('Example monitor renamed')
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.waitForURL('/monitors')
    await expect(page.getByText('Example monitor renamed')).toBeVisible()

    await page.getByRole('button', { name: 'Pause monitor' }).click()
    await expect(page.getByText('Paused', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Resume monitor' }).click()
    await expect(page.getByText('New', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page.getByText('Check queued.')).toBeVisible()

    await page.getByRole('button', { name: 'Delete monitor' }).click()
    await page.getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByText('Example monitor renamed')).not.toBeVisible()
  })

  test('pause rolls back on a failed request', async ({ page }) => {
    // Seeded via the dev fixture, not the real create-monitor form — this test is about the
    // pause mutation's rollback, not creation, and the extra UI round-trip was eating enough of
    // this sandbox's slow-host time budget to starve the actual assertion below its own window.
    const email = uniqueEmail('pw-monitors')
    await createDevUser(email, TEST_PASSWORD)
    await seedMonitors(email, 1)
    await loginViaUi(page, email, TEST_PASSWORD)

    await gotoRetrying(page, '/monitors')
    await expect(page.getByText('Chaos — healthy')).toBeVisible()

    await page.route('**/api/v1/monitors/*/pause', (route) => route.abort('failed'))
    await page.getByRole('button', { name: 'Pause monitor' }).click()

    // Optimistic update fires, then rolls back once the request fails.
    await expect(page.getByText('Paused', { exact: true })).toHaveCount(0)
  })

  test('a blocked URL shows a friendly inline field error', async ({ page }) => {
    const email = uniqueEmail('pw-monitors')
    await createDevUser(email, TEST_PASSWORD)
    await loginViaUi(page, email, TEST_PASSWORD)

    await gotoRetrying(page, '/monitors/new')
    await page.getByLabel('Name').fill('Blocked')
    // A literal private-IP host is denied synchronously (no DNS lookup needed), unlike a
    // hostname that resolves to one — keeps this test independent of outbound DNS/internet
    // access in the test environment.
    await page.getByLabel('URL').fill('http://127.0.0.1:9000/')
    await page.getByRole('button', { name: 'Create monitor' }).click()
    await expect(page.getByRole('alert')).toContainText(/private or internal address/i)
  })
})

test.describe('plan limit', () => {
  test.use({ storageState: FIXTURES.limit.statePath })

  test('create is disabled and the usage bar reads 15 / 15', async ({ page }) => {
    await gotoRetrying(page, '/monitors')
    await expect(page.getByText("You've reached your plan's monitor limit.")).toBeVisible()
    await expect(page.getByRole('button', { name: 'New monitor' })).toBeDisabled()
    await expect(page.getByText('15 / 15')).toBeVisible()
  })
})

test.describe('unverified account', () => {
  test.use({ storageState: FIXTURES.unverifiedMonitors.statePath })

  test('create is disabled with verification-required copy', async ({ page }) => {
    await gotoRetrying(page, '/monitors')
    await expect(page.getByText('Verify your email to create monitors.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'New monitor' })).toBeDisabled()
  })
})
