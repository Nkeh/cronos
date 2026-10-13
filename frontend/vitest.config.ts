import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Playwright owns tests/e2e/*.spec.ts — without this, vitest tries to run them too and
    // fails on the @playwright/test fixtures (browser, page, …) it doesn't provide.
    exclude: ['**/node_modules/**', 'tests/e2e/**'],
  },
})
