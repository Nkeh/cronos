import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dirname = path.dirname(fileURLToPath(import.meta.url))

function statePath(name: string): string {
  return path.join(dirname, '..', '..', 'screenshots', `.auth-state-${name}.json`)
}

export const SHARED_PASSWORD = 'CorrectHorseBattery9'

/**
 * Fixture accounts created once in global-setup.ts via the dev-only /api/v1/_dev/* endpoints
 * (never real signup — see helpers/dev-fixtures.ts), each with its own storageState file so
 * read-only specs (axe, screenshots, navbar geometry) can run in parallel without colliding on
 * the same account's rows. Tests that mutate monitor state get their own fresh per-test user
 * instead (see monitors.spec.ts) — these four are for specs that only need to *read* a known,
 * stable shape.
 */
export const FIXTURES = {
  /** Verified, zero monitors. */
  emptyMonitors: {
    email: 'pw-empty-monitors@example.com',
    password: SHARED_PASSWORD,
    statePath: statePath('emptyMonitors'),
  },
  /** Verified, ~6 monitors via seed-demo's fixed demo shape (one paused). */
  seeded: {
    email: 'pw-seeded-user@example.com',
    password: SHARED_PASSWORD,
    statePath: statePath('seeded'),
  },
  /** Verified, exactly 15 monitors — at the launch plan's limit. */
  limit: {
    email: 'pw-limit-user@example.com',
    password: SHARED_PASSWORD,
    statePath: statePath('limit'),
  },
  /** Created without --verified. */
  unverifiedMonitors: {
    email: 'pw-unverified-monitors@example.com',
    password: SHARED_PASSWORD,
    statePath: statePath('unverifiedMonitors'),
  },
} as const

// Kept for specs/pages not specific to monitors (navbar width/aria tests on "/", the overview
// axe/screenshot pass) — same account as emptyMonitors, just the long-standing name.
export const SHARED_EMAIL = FIXTURES.emptyMonitors.email
export const AUTH_STATE_PATH = FIXTURES.emptyMonitors.statePath
