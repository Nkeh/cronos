import { test, type Browser, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gotoRetrying } from './helpers/auth'
import { AUTH_STATE_PATH, FIXTURES } from './helpers/shared-user'

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
  /** Either a static path to navigate to, or a function that leaves the page at the desired
   * location itself (e.g. clicking into a specific monitor's edit screen, whose id isn't known
   * statically). */
  path: string | ((page: Page) => Promise<void>)
}

const UNAUTH_PAGES: PageSpec[] = [
  { name: 'login', path: '/login' },
  { name: 'signup', path: '/signup' },
  { name: 'verify', path: '/verify' },
  { name: 'forgot', path: '/forgot' },
  { name: 'reset', path: '/reset' },
  { name: 'dev-design', path: '/dev/design' },
]

const AUTH_PAGES: PageSpec[] = [
  { name: 'overview', path: '/' },
  { name: 'monitors-empty', path: '/monitors' },
  { name: 'monitor-new', path: '/monitors/new' },
]

const SEEDED_PAGES: PageSpec[] = [
  { name: 'overview-seeded', path: '/' },
  { name: 'monitors-seeded', path: '/monitors' },
  {
    name: 'monitor-edit',
    path: async (page) => {
      await gotoRetrying(page, '/monitors')
      await page.getByRole('link', { name: 'Edit monitor' }).first().click()
      await page.waitForURL(/\/monitors\/.+\/edit/, { timeout: 15000 })
    },
  },
]

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
        if (typeof p.path === 'string') {
          // Bounded retry, not a longer single timeout — this sandbox's dev server occasionally
          // stalls a navigation well past 15s under host CPU contention (see docs/progress), and
          // this test's generous 10-minute budget (unlike the 30s-per-test default) has plenty
          // of room to absorb one retry without masking a real hang.
          await gotoRetrying(page, p.path)
        } else {
          await p.path(page)
        }
        for (const width of WIDTHS) {
          await page.setViewportSize({ width, height: 900 })
          // animations: 'disabled' finishes/skips any running CSS transition or animation
          // before the capture, deterministically — no arbitrary sleep needed to "let it settle".
          await page.screenshot({
            path: path.join(dir, `${width}-${theme}-${motion.label}.png`),
            fullPage: true,
            animations: 'disabled',
            timeout: 15000,
          })
        }
      }
      await context.close()
    }
  }
}

// @screenshots — run in a separate invocation from the default suite (--grep @screenshots /
// --grep-invert @screenshots), so its own longer timeout doesn't widen the default run's and so
// it never contends with other specs for the dev server/CPU.
test('capture the screenshot matrix @screenshots', async ({ browser }) => {
  // 144 screenshots (12 pages x 3 widths x 2 themes x 2 motion) consistently finish inside 10
  // minutes on this sandbox, but teardown of the final context can still cross that line by a
  // few seconds under host CPU contention — the capture itself always completes first.
  test.setTimeout(12 * 60 * 1000)
  await captureGroup(browser, UNAUTH_PAGES)
  // Authenticated pages need a session — reuse fixture accounts from global-setup.ts rather
  // than signing up again (keeps this independent of the signup rate limit entirely).
  await captureGroup(browser, AUTH_PAGES, AUTH_STATE_PATH)
  await captureGroup(browser, SEEDED_PAGES, FIXTURES.seeded.statePath)
})
