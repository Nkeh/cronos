import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Playwright owns tests/e2e/*.spec.ts — without this, vitest tries to run them too and
    // fails on the @playwright/test fixtures (browser, page, …) it doesn't provide.
    exclude: ['**/node_modules/**', 'tests/e2e/**'],
    // Whichever test mounts the first Radix Dialog/Drawer tree in a given worker pays a one-time
    // jsdom + portal cold-start cost that can land anywhere from ~2.5s to just past the 5000ms
    // default under this container's CPU budget (4 cores, shared with the rest of the compose
    // stack) -- not a hang, confirmed by re-running the same test alone well under budget. Raised
    // once here instead of per-test so it doesn't become whack-a-mole as test files are added.
    testTimeout: 15000,
  },
})
