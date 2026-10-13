import { apiRequest } from './client'
import type { UsageResponse } from './types'

export function getUsage() {
  return apiRequest<UsageResponse>('/api/v1/usage')
}
