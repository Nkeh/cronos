import { afterEach, describe, expect, it, vi } from 'vitest'
import { checkApiStatus } from './client'

describe('checkApiStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns "up" when /healthz responds ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true } as Response),
    )
    await expect(checkApiStatus()).resolves.toBe('up')
  })

  it('returns "down" when /healthz responds with a non-ok status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false } as Response),
    )
    await expect(checkApiStatus()).resolves.toBe('down')
  })

  it('returns "down" when the request throws (network error)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(checkApiStatus()).resolves.toBe('down')
  })
})
