import { request as playwrightRequest } from '@playwright/test'

/**
 * Direct control of the chaos target's per-path behavior (POST /_control -- app/main.py in
 * chaos/), the same mechanism the backend's own live-acceptance testing uses (see
 * docs/progress/day-08.md). Reached at chaos's own internal address, not through Caddy (Caddy
 * only proxies /api and /ping to the real api service, never to chaos) -- works because
 * pw-tests-e2e shares caddy-e2e's network namespace, which is on the same `default` compose
 * network as chaos.
 */
const CHAOS_BASE_URL = 'http://chaos:8000'
const REQUEST_TIMEOUT_MS = 10000

export type ChaosMode = 'up' | 'down' | 'slow' | 'flap' | 'hang' | 'redirect' | 'big' | 'tls_bad'

export async function setChaosMode(
  path: string,
  mode: ChaosMode,
  opts: { status_code?: number } = {},
): Promise<void> {
  const api = await playwrightRequest.newContext({ baseURL: CHAOS_BASE_URL })
  try {
    const resp = await api.post('/_control', {
      data: { path, mode, status_code: opts.status_code ?? 503 },
      timeout: REQUEST_TIMEOUT_MS,
    })
    if (!resp.ok()) {
      throw new Error(`chaos control failed: ${resp.status()} ${await resp.text()}`)
    }
  } finally {
    await api.dispose()
  }
}
