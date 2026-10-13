export interface UserPublic {
  user_id: string
  email: string
  email_verified: boolean
  account_id: string
  plan: string
}

export interface UsageCounts {
  monitors: number
  heartbeats: number
  status_pages: number
  api_keys: number
}

export interface UsageResponse {
  plan: string
  limits: Record<string, number | boolean>
  counts: UsageCounts
  launch_period: boolean
}

export interface MessageResponse {
  message: string
}
