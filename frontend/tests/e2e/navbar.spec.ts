import { test, expect } from '@playwright/test'
import { gotoRetrying } from './helpers/auth'
import { AUTH_STATE_PATH, FIXTURES } from './helpers/shared-user'

test.use({ storageState: AUTH_STATE_PATH })

const widths = [375, 768, 1440]

for (const width of widths) {
  test(`navbar geometry and aria-current at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await gotoRetrying(page, '/')

    // The <nav> landmark is a full-width positioning container (it centers its child); the
    // capsule itself is the visually-bounded element the "never edge-to-edge" rule applies to.
    const capsule = page.getByTestId('navbar-capsule')
    const capsuleBox = await capsule.boundingBox()
    expect(capsuleBox).toBeTruthy()
    expect(capsuleBox!.x).toBeGreaterThanOrEqual(15)
    expect(width - (capsuleBox!.x + capsuleBox!.width)).toBeGreaterThanOrEqual(15)

    await expect(page.getByRole('link', { name: 'Overview' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
}

test('full keyboard reach into the navbar', async ({ page }) => {
  await page.goto('/')

  let reachedNav = false
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press('Tab')
    const inNav = await page.evaluate(() => {
      const active = document.activeElement
      const nav = document.querySelector('nav[aria-label="Primary"]')
      return !!(active && nav && nav.contains(active))
    })
    if (inNav) {
      reachedNav = true
      break
    }
  }
  expect(reachedNav).toBe(true)
})

test('active pill moves between routes under reduced motion (MotionConfig reducedMotion="user")', async ({
  page,
}) => {
  // Motion's shared-layoutId spring drives the pill via WAAPI/transform, not a CSS `transition`,
  // so there's no reliable CSS property to probe for "no animation." What's actually testable:
  // MotionConfig reducedMotion="user" is wired up, and the active state still updates correctly.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')

  await page.getByRole('link', { name: 'Monitors' }).click()
  await expect(page.getByRole('link', { name: 'Monitors' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current', 'page')
})

for (const width of widths) {
  test(`last monitor row is visible above the navbar when scrolled to the bottom at ${width}px`, async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: FIXTURES.seeded.statePath })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: 700 })
    await gotoRetrying(page, '/monitors')

    const rows = page.getByRole('link', { name: 'Edit monitor' })
    // Wait for the real rows to replace the loading skeleton before measuring scroll height —
    // scrolling against the skeleton's (much shorter) layout would land short of the real bottom.
    await rows.first().waitFor()
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))

    await expect(rows.last()).toBeInViewport()
    const nav = page.getByRole('navigation', { name: 'Primary' })
    await expect(nav).toBeInViewport()
    await context.close()
  })
}
