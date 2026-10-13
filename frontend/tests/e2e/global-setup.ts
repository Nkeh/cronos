import fs from 'node:fs'
import path from 'node:path'
import { chromium, type FullConfig } from '@playwright/test'
import { signupVerifyLogin } from './helpers/auth'
import { AUTH_STATE_PATH, SHARED_EMAIL, SHARED_PASSWORD } from './helpers/shared-user'

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? 'http://localhost:8080'
  const browser = await chromium.launch()
  const page = await browser.newPage({ baseURL })

  await signupVerifyLogin(page, SHARED_EMAIL, SHARED_PASSWORD)

  fs.mkdirSync(path.dirname(AUTH_STATE_PATH), { recursive: true })
  await page.context().storageState({ path: AUTH_STATE_PATH })
  await browser.close()
}
