export type ApiStatus = 'up' | 'down'

export async function checkApiStatus(signal?: AbortSignal): Promise<ApiStatus> {
  try {
    const response = await fetch('/healthz', { signal })
    return response.ok ? 'up' : 'down'
  } catch {
    return 'down'
  }
}
