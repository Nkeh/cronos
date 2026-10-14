import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  // Day 5b: fixture users now come from the dev-only /_dev endpoints (helpers/dev-fixtures.ts),
  // not real signup, and dev rate limits were raised (.env) — the original constraint (every
  // request shares one IP via network_mode: service:caddy, signup capped at 5/hour) no longer
  // applies to most specs. auth.spec.ts's own 4 signup/verify/forgot/reset tests still go
  // through real signup, but 4/run is well under even the un-raised cap.
  //
  // workers is pinned to 1 despite fullyParallel: true. Measured directly (docs/progress/day-05b)
  // — 2 workers against this sandbox's dev server (WATCH_POLLING-mode chokidar on a Windows bind
  // mount) was enough contention to blow the 30s per-test timeout on form fills and navigations
  // that take ~1-2s running alone. The user's instruction fixed the 30s test timeout as a hard
  // ceiling rather than something to raise, so concurrency is the dial that has to move instead.
  fullyParallel: true,
  workers: 1,
  retries: 0,
  // 'line' prints one line per test as it finishes (not just at the end) — a hang shows up
  // immediately as "nothing printing", not as silence until some outer wrapper's EOF.
  reporter: 'line',
  // Hard ceilings so a stuck test or a stuck run fails loudly instead of hanging indefinitely —
  // this is the direct fix for two prior sessions where a Playwright invocation produced no
  // output and no exit for over an hour (once for 13 hours). globalTimeout bounds the WHOLE
  // run regardless of how many tests exist; timeout bounds each test; expect.timeout bounds
  // each assertion inside a test. All three are enforced by Playwright itself, independent of
  // whatever wraps the process on the outside.
  globalTimeout: 15 * 60 * 1000,
  timeout: 30000,
  expect: { timeout: 10000 },
  globalSetup: './tests/e2e/global-setup.ts',
  use: {
    baseURL: 'http://localhost:8080',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
