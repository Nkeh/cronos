import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  // Serial, single-worker: every request shares one IP (network_mode: service:caddy) and
  // signup is rate-limited to 5/hour per IP, so bursts of concurrent signups 429.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  // Real Mailpit round-trips + multiple navigations push some auth flows past the 30s default.
  timeout: 60000,
  globalSetup: './tests/e2e/global-setup.ts',
  use: {
    baseURL: 'http://localhost:8080',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
