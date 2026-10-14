import fs from 'node:fs'
import path from 'node:path'
import { chromium, type FullConfig } from '@playwright/test'
import { createDevUser, deleteDevUser, seedMonitors } from './helpers/dev-fixtures'
import { loginViaUi } from './helpers/auth'
import { FIXTURES } from './helpers/shared-user'
import { withDeadline } from './helpers/deadline'

// auth.ts's gotoRetrying allows one retry at 20s each on login navigation — give login steps
// enough headroom that retry doesn't trip this outer deadline too.
const STEP_TIMEOUT_MS = 20000
const LOGIN_STEP_TIMEOUT_MS = 45000
const BROWSER_LAUNCH_TIMEOUT_MS = 30000

export default async function globalSetup(config: FullConfig) {
  const started = Date.now()
  const log = (message: string) => {
    console.log(`[global-setup +${((Date.now() - started) / 1000).toFixed(1)}s] ${message}`)
  }

  const baseURL = config.projects[0]?.use.baseURL ?? 'http://localhost:8080'
  log('launching browser')
  const browser = await chromium.launch({ timeout: BROWSER_LAUNCH_TIMEOUT_MS })

  async function saveLoggedInState(email: string, password: string, statePath: string) {
    const page = await browser.newPage({ baseURL })
    try {
      await withDeadline(
        loginViaUi(page, email, password),
        LOGIN_STEP_TIMEOUT_MS,
        `log in as ${email}`,
      )
      fs.mkdirSync(path.dirname(statePath), { recursive: true })
      await page.context().storageState({ path: statePath })
    } finally {
      await page.close()
    }
  }

  const { emptyMonitors, seeded, limit, unverifiedMonitors } = FIXTURES

  try {
    // The dev database persists across runs (unlike the test database), so these fixture
    // accounts aren't naturally idempotent to recreate — reset each one first.
    for (const fixture of [emptyMonitors, seeded, limit, unverifiedMonitors]) {
      log(`resetting fixture ${fixture.email}`)
      await withDeadline(
        deleteDevUser(fixture.email),
        STEP_TIMEOUT_MS,
        `delete fixture ${fixture.email}`,
      )
    }

    log(`creating fixture ${emptyMonitors.email}`)
    await withDeadline(
      createDevUser(emptyMonitors.email, emptyMonitors.password),
      STEP_TIMEOUT_MS,
      `create fixture ${emptyMonitors.email}`,
    )
    await saveLoggedInState(emptyMonitors.email, emptyMonitors.password, emptyMonitors.statePath)

    log(`creating fixture ${seeded.email}`)
    await withDeadline(
      createDevUser(seeded.email, seeded.password),
      STEP_TIMEOUT_MS,
      `create fixture ${seeded.email}`,
    )
    await withDeadline(seedMonitors(seeded.email, 6), STEP_TIMEOUT_MS, `seed monitors for ${seeded.email}`)
    await saveLoggedInState(seeded.email, seeded.password, seeded.statePath)

    log(`creating fixture ${limit.email}`)
    await withDeadline(
      createDevUser(limit.email, limit.password),
      STEP_TIMEOUT_MS,
      `create fixture ${limit.email}`,
    )
    await withDeadline(seedMonitors(limit.email, 15), STEP_TIMEOUT_MS, `seed monitors for ${limit.email}`)
    await saveLoggedInState(limit.email, limit.password, limit.statePath)

    log(`creating fixture ${unverifiedMonitors.email}`)
    await withDeadline(
      createDevUser(unverifiedMonitors.email, unverifiedMonitors.password, false),
      STEP_TIMEOUT_MS,
      `create fixture ${unverifiedMonitors.email}`,
    )
    await saveLoggedInState(
      unverifiedMonitors.email,
      unverifiedMonitors.password,
      unverifiedMonitors.statePath,
    )

    log('done')
  } finally {
    await withDeadline(browser.close(), 10000, 'close browser')
  }
}
