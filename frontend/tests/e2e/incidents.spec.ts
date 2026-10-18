import { test, expect } from '@playwright/test'
import { gotoRetrying } from './helpers/auth'
import { setChaosMode } from './helpers/chaos'
import { createOpenIncident } from './helpers/incident-fixture'

test.describe('incident lifecycle', () => {
  test('chaos down -> incident + badge -> detail -> ack -> chaos up -> resolves + badge clears', async ({
    page,
  }) => {
    // The fixture's own check-now round trip plus a second one for recovery, each waiting out
    // a runner tick (~2s) and a bounded poll for the badge/list to catch up -- comfortably
    // inside 60s, past the file-wide 30s default.
    test.setTimeout(60000)

    const fixture = await createOpenIncident(page, 'incidents')
    // createOpenIncident leaves the page on /incidents with the open incident visible.
    await expect(page.getByRole('link', { name: fixture.monitorName })).toBeVisible()
    await expect(page.getByText('ongoing')).toBeVisible()

    await test.step('detail page: timeline + acknowledge', async () => {
      await page.getByRole('link', { name: fixture.monitorName }).click()
      await page.waitForURL(/\/incidents\/.+/)
      await expect(page.getByText('Open', { exact: true })).toBeVisible()
      await expect(page.getByText('Started')).toBeVisible()

      await page.getByRole('button', { name: 'Acknowledge' }).click()
      await expect(page.getByRole('button', { name: 'Acknowledged' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Acknowledged' })).toBeDisabled()
    })

    await setChaosMode(fixture.chaosPath, 'up')

    await test.step('recovery: check-now resolves it, badge clears', async () => {
      await gotoRetrying(page, '/monitors')
      await page.getByRole('button', { name: 'Check now' }).click()
      await expect(page.getByText('Check queued.')).toBeVisible()

      // Poll the genuinely unambiguous target state directly, not the badge's absence as a
      // proxy for it -- IncidentsBadge renders nothing both while truly at zero AND while its
      // query is still loading, so an early reload can read "no badge" before the resolution
      // has actually landed, passing the gate on the wrong event (found live: this exact race
      // let the test move on while the incident was still open).
      await expect(async () => {
        await gotoRetrying(page, '/incidents')
        await expect(page.getByText('resolved Recovered')).toBeVisible()
      }).toPass({ timeout: 30000, intervals: [1000, 2000, 3000, 5000] })

      // Now that resolution is confirmed, the badge being gone is no longer ambiguous.
      await page.reload()
      await expect(page.getByTestId('incidents-badge')).toHaveCount(0)
    })
  })
})
