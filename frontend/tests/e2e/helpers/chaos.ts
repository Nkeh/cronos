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
  opts: {
    status_code?: number
    // Day 9: /webhook-only fields, driven through this same /_control machinery -- see
    // chaos/app/main.py's ControlEntry. response_sequence lets a retry test script e.g.
    // [500, 500, 200]; webhook_secret lets a test assert verified=true in /_webhook/_log.
    webhook_secret?: string
    response_sequence?: number[]
  } = {},
): Promise<void> {
  const api = await playwrightRequest.newContext({ baseURL: CHAOS_BASE_URL })
  try {
    const resp = await api.post('/_control', {
      data: {
        path,
        mode,
        status_code: opts.status_code ?? 503,
        webhook_secret: opts.webhook_secret,
        response_sequence: opts.response_sequence,
      },
      timeout: REQUEST_TIMEOUT_MS,
    })
    if (!resp.ok()) {
      throw new Error(`chaos control failed: ${resp.status()} ${await resp.text()}`)
    }
  } finally {
    await api.dispose()
  }
}

export interface WebhookLogEntry {
  delivery_id: string | null
  event: string | null
  signature_header: string | null
  body_length: number
  verified: boolean | null
  arrived_at: number
}

export async function getWebhookLog(): Promise<WebhookLogEntry[]> {
  const api = await playwrightRequest.newContext({ baseURL: CHAOS_BASE_URL })
  try {
    const resp = await api.get('/_webhook/_log', { timeout: REQUEST_TIMEOUT_MS })
    if (!resp.ok()) {
      throw new Error(`chaos webhook log fetch failed: ${resp.status()}`)
    }
    return (await resp.json()) as WebhookLogEntry[]
  } finally {
    await api.dispose()
  }
}
