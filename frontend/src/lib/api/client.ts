import { ApiError, type ApiErrorBody } from './errors'

export type ApiStatus = 'up' | 'down'

export async function checkApiStatus(signal?: AbortSignal): Promise<ApiStatus> {
  try {
    const response = await fetch('/healthz', { signal })
    return response.ok ? 'up' : 'down'
  } catch {
    return 'down'
  }
}

const CSRF_COOKIE_NAME = 'cronos_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : null
}

/** Primes the `cronos_csrf` cookie. Called at boot and once as a retry after `csrf_failed`. */
export async function fetchCsrfToken(): Promise<void> {
  await fetch('/api/v1/auth/csrf', { credentials: 'same-origin' })
}

async function rawRequest(path: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (WRITE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE_NAME)
    if (token) headers.set(CSRF_HEADER_NAME, token)
    if (init.body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
  }
  return fetch(path, { ...init, method, headers, credentials: 'same-origin' })
}

/**
 * Same-origin JSON client for /api/v1. Retries once on `403 csrf_failed` after refreshing the
 * CSRF cookie; maps every other non-2xx response onto a typed ApiError.
 */
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response = await rawRequest(path, init)

  if (response.status === 403) {
    const peek = await response
      .clone()
      .json()
      .catch(() => null)
    if (peek?.error?.code === 'csrf_failed') {
      await fetchCsrfToken()
      response = await rawRequest(path, init)
    }
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const retryAfterHeader = response.headers.get('Retry-After')
    const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : undefined
    const errorBody: ApiErrorBody = body?.error ?? {
      code: 'unknown_error',
      message: response.statusText || 'Something went wrong.',
    }
    throw new ApiError(response.status, errorBody, retryAfter)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
