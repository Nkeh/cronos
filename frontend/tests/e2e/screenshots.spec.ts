import { test, type Browser } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { AUTH_STATE_PATH } from './helpers/shared-user'

const dirname = path.dirname(fileURLToPath(import.meta.url))
const SCREENSHOT_DIR = path.join(dirname, '..', 'screenshots')
const WIDTHS = [375, 768, 1440] as const
const THEMES = ['light', 'dark'] as const
const MOTION = [
  { label: 'motion-on', reducedMotion: 'no-preference' as const },
  { label: 'motion-off', reducedMotion: 'reduce' as const },
]

interface PageSpec {
  name: string
  path: string
}

const UNAUTH_PAGES: PageSpec[] = [
  { name: 'login', path: '/login' },
  { name: 'signup', path: '/signup' },
  { name: 'verify', path: '/verify' },
  { name: 'forgot', path: '/forgot' },
  { name: 'reset', path: '/reset' },
  { name: 'dev-design', path: '/dev/design' },
]

const AUTH_PAGES: PageSpec[] = [{ name: 'overview', path: '/' }]

// One context per (theme x motion) combo, reused across every page/width in the group — far
// fewer context creations than one per screenshot, which is what made this test time out.
async function captureGroup(browser: Browser, pages: PageSpec[], storageState?: string) {
  for (const theme of THEMES) {
    for (const motion of MOTION) {
      const context = await browser.newContext({
        colorScheme: theme,
        reducedMotion: motion.reducedMotion,
        storageState,
      })
      const page = await context.newPage()
      for (const p of pages) {
        const dir = path.join(SCREENSHOT_DIR, p.name)
        fs.mkdirSync(dir, { recursive: true })
        // Navigate once per page, not per width — a responsive layout reflows on resize alone,
        // so re-navigating for every width tripled the number of full page loads for nothing.
        await page.goto(p.path, { waitUntil: 'domcontentloaded' })
        for (const width of WIDTHS) {
          await page.setViewportSize({ width, height: 900 })
          await page.waitForTimeout(150)
          await page.screenshot({
            path: path.join(dir, `${width}-${theme}-${motion.label}.png`),
            fullPage: true,
          })
        }
      }
      await context.close()
    }
  }
}

test('capture the Part A screenshot matrix', async ({ browser }) => {
  test.setTimeout(9 * 60 * 1000)
  await captureGroup(browser, UNAUTH_PAGES)
  // Overview needs an authenticated session — reuse the shared user from global-setup.ts
  // rather than signing up again (signup is rate-limited to 5/hour per IP).
  await captureGroup(browser, AUTH_PAGES, AUTH_STATE_PATH)
})
