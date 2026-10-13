import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './client'
import { ApiError } from './errors'

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers })
}

describe('apiRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.cookie = 'cronos_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('returns the parsed body on a 2xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, { ok: true })))
    await expect(apiRequest('/api/v1/auth/me')).resolves.toEqual({ ok: true })
  })

  it('returns undefined for a 204 response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(apiRequest('/api/v1/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('sends the X-CSRF-Token header from the cronos_csrf cookie on a write', async () => {
    document.cookie = 'cronos_csrf=test-token'
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)

    await apiRequest('/api/v1/monitors', { method: 'POST', body: JSON.stringify({}) })

    const [, init] = fetchMock.mock.calls[0]
    const headers = init.headers as Headers
    expect(headers.get('X-CSRF-Token')).toBe('test-token')
  })

  it('maps a non-2xx response onto a typed ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(401, { error: { code: 'invalid_credentials', message: 'Nope.' } }),
      ),
    )

    await expect(apiRequest('/api/v1/auth/login', { method: 'POST' })).rejects.toMatchObject({
      code: 'invalid_credentials',
      status: 401,
    })
  })

  it('parses Retry-After into ApiError.retryAfter on a 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          429,
          { error: { code: 'rate_limited', message: 'Slow down.' } },
          { 'Retry-After': '30' },
        ),
      ),
    )

    try {
      await apiRequest('/api/v1/auth/login', { method: 'POST' })
      expect.unreachable()
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).retryAfter).toBe(30)
    }
  })

  it('on 403 csrf_failed, refreshes the CSRF cookie and retries the request once', async () => {
    let callCount = 0
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      callCount += 1
      if (path === '/api/v1/auth/csrf') {
        document.cookie = 'cronos_csrf=fresh-token'
        return Promise.resolve(new Response('{}', { status: 200 }))
      }
      if (callCount === 1) {
        return Promise.resolve(
          jsonResponse(403, { error: { code: 'csrf_failed', message: 'Bad token.' } }),
        )
      }
      return Promise.resolve(jsonResponse(200, { ok: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiRequest('/api/v1/monitors', { method: 'POST', body: JSON.stringify({}) }),
    ).resolves.toEqual({ ok: true })

    // original request, csrf refresh, retried request
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not retry a 403 that is not csrf_failed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(403, { error: { code: 'insufficient_scope', message: 'No.' } }),
      ),
    )

    await expect(apiRequest('/api/v1/monitors')).rejects.toMatchObject({
      code: 'insufficient_scope',
    })
  })
})
