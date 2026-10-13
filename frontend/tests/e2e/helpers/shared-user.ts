import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * Signup is rate-limited to 5/hour per IP (app/core/config.py), and every request from this
 * container shares one IP via `network_mode: service:caddy`. Most specs reuse this single
 * verified, logged-in account via storageState (see global-setup.ts) instead of signing up fresh
 * — only the handful of tests that exercise the signup/forgot/reset flows themselves create their
 * own account.
 */
export const SHARED_EMAIL = 'pw-shared-user@example.com'
export const SHARED_PASSWORD = 'CorrectHorseBattery9'
export const AUTH_STATE_PATH = path.join(dirname, '..', '..', 'screenshots', '.auth-state.json')
