import { expect, type Page } from '@playwright/test'
import { createDevUser } from './dev-fixtures'
import { gotoRetrying, loginViaUi, uniqueEmail, TEST_PASSWORD } from './auth'
import { setChaosMode } from './chaos'

export interface MonitorIncidentFixture {
  monitorName: string
  chaosPath: string
}

/** Creates a fresh dev user and logs in through the real UI. Everything below assumes the page
 * is already authenticated this way, and that the account has (at most) the one monitor this
 * module itself creates -- check-now targeting below assumes exactly one such button exists. */
export async function createDevAccountAndLogin(page: Page, label: string): Promise<string> {
  const email = uniqueEmail(label)
  await createDevUser(email, TEST_PASSWORD)
  await loginViaUi(page, email, TEST_PASSWORD)
  return email
}

/**
 * On an already-logged-in, monitor-less page, creates a monitor pointed at an already-down,
 * uniquely-named chaos path with confirm_threshold=1 (so the incident opens on the very first
 * failed check, no 30s re-check wait), triggers check-now, and waits for the navbar badge to
 * confirm the incident opened. Leaves the page on /incidents with it visible.
 */
export async function openIncidentOnNewMonitor(
  page: Page,
  label: string,
): Promise<MonitorIncidentFixture> {
  const chaosPath = `/e2e-${label}-${Date.now()}`
  const monitorName = `E2E ${label} target`
  await setChaosMode(chaosPath, 'down')

  await gotoRetrying(page, '/monitors/new')
  await page.getByLabel('Name').fill(monitorName)
  await page.getByLabel('URL').fill(`http://chaos:8000${chaosPath}`)
  await page.getByRole('button', { name: 'Advanced' }).click()
  await page.getByLabel('Confirm threshold').fill('1')
  await page.getByRole('button', { name: 'Create monitor' }).click()
  await page.waitForURL('/monitors')

  await page.getByRole('button', { name: 'Check now' }).click()

  await expect(async () => {
    await page.reload()
    await expect(page.getByTestId('incidents-badge')).toHaveText('1')
  }).toPass({ timeout: 20000, intervals: [1000, 2000, 3000] })

  await gotoRetrying(page, '/incidents')
  return { monitorName, chaosPath }
}

/** Resolves a fixture from openIncidentOnNewMonitor by flipping its chaos path back up and
 * re-running check-now, polling /incidents directly for the resolved row. Assumes this is still
 * the only monitor on the account (one check-now button). Leaves the page on /incidents.
 *
 * Polls the resolved row itself, not the navbar badge's absence as a proxy for it --
 * IncidentsBadge renders nothing both while truly at zero AND while its query is still loading,
 * so an early reload can read "no badge" before the resolution has actually landed (found live
 * in incidents.spec.ts's lifecycle test, which hit exactly this race). */
export async function resolveIncident(page: Page, fixture: MonitorIncidentFixture): Promise<void> {
  await setChaosMode(fixture.chaosPath, 'up')

  await gotoRetrying(page, '/monitors')
  await page.getByRole('button', { name: 'Check now' }).click()

  await expect(async () => {
    await gotoRetrying(page, '/incidents')
    await expect(page.getByText('resolved Recovered')).toBeVisible()
  }).toPass({ timeout: 30000, intervals: [1000, 2000, 3000, 5000] })
}

/** The common single-incident case used by incidents.spec.ts and axe.spec.ts: fresh account,
 * one monitor, one open incident. */
export async function createOpenIncident(
  page: Page,
  label: string,
): Promise<MonitorIncidentFixture & { email: string }> {
  const email = await createDevAccountAndLogin(page, label)
  const fixture = await openIncidentOnNewMonitor(page, label)
  return { email, ...fixture }
}
