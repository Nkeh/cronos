import { request as playwrightRequest, type APIRequestContext } from '@playwright/test'

/**
 * Thin wrappers over the dev-only /api/v1/_dev/* endpoints (app/dev/router.py), which share the
 * exact same logic as `python -m app.cli`. Used instead of the CLI directly because the
 * pw-tests container has no Docker access to shell into the api container — this gives
 * Playwright the same network-native access it already has to the API and Mailpit.
 *
 * These are POSTs, so they're subject to the same blanket CSRF double-submit middleware as
 * every other mutating /api request (app/core/csrf.py) — fetch the cookie via GET /auth/csrf
 * first and echo it back as the X-CSRF-Token header, same as the frontend's own apiRequest().
 *
 * Every request below carries an explicit `timeout` — an APIRequestContext call has no default
 * ceiling of its own, so a stuck server (or a stuck Docker network) would otherwise hang the
 * whole globalSetup, and therefore the whole run, with no error at all.
 */
const BASE_URL = 'http://localhost:8080'
const REQUEST_TIMEOUT_MS = 10000

function readCsrfCookie(setCookieHeaders: string[]): string | null {
  for (const header of setCookieHeaders) {
    const match = header.match(/^cronos_csrf=([^;]+)/)
    if (match) return decodeURIComponent(match[1])
  }
  return null
}

async function withApiContext<T>(
  fn: (api: APIRequestContext, csrfHeaders: Record<string, string>) => Promise<T>,
): Promise<T> {
  const api = await playwrightRequest.newContext({ baseURL: BASE_URL })
  try {
    const csrfResp = await api.get('/api/v1/auth/csrf', { timeout: REQUEST_TIMEOUT_MS })
    const allHeaders = await csrfResp.headersArray()
    const setCookie = allHeaders.filter((h) => h.name.toLowerCase() === 'set-cookie')
    const token = readCsrfCookie(setCookie.map((h) => h.value))
    if (!token) throw new Error('dev fixture: could not read cronos_csrf cookie from /auth/csrf')

    return await fn(api, { 'X-CSRF-Token': token })
  } finally {
    await api.dispose()
  }
}

export async function createDevUser(
  email: string,
  password: string,
  verified = true,
): Promise<void> {
  await withApiContext(async (api, csrfHeaders) => {
    const resp = await api.post('/api/v1/_dev/users', {
      data: { email, password, verified },
      headers: csrfHeaders,
      timeout: REQUEST_TIMEOUT_MS,
    })
    if (!resp.ok()) {
      throw new Error(`dev fixture create-user failed: ${resp.status()} ${await resp.text()}`)
    }
  })
}

/** Idempotent — deleting a nonexistent email is a no-op server-side. Used by global-setup to
 * reset fixture accounts, since the dev database (unlike the test database) persists across
 * Playwright runs. */
export async function deleteDevUser(email: string): Promise<void> {
  await withApiContext(async (api, csrfHeaders) => {
    const resp = await api.post('/api/v1/_dev/users/delete', {
      data: { email },
      headers: csrfHeaders,
      timeout: REQUEST_TIMEOUT_MS,
    })
    if (!resp.ok()) {
      throw new Error(`dev fixture delete-user failed: ${resp.status()} ${await resp.text()}`)
    }
  })
}

export async function seedMonitors(email: string, count: number): Promise<void> {
  await withApiContext(async (api, csrfHeaders) => {
    const resp = await api.post('/api/v1/_dev/seed-monitors', {
      data: { email, count },
      headers: csrfHeaders,
      timeout: REQUEST_TIMEOUT_MS,
    })
    if (!resp.ok()) {
      throw new Error(`dev fixture seed-monitors failed: ${resp.status()} ${await resp.text()}`)
    }
  })
}
