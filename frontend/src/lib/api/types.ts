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

export type MonitorStatus = 'new' | 'up' | 'down' | 'paused'
export type MonitorMethod = 'GET' | 'HEAD'

export interface Monitor {
  id: string
  name: string
  url: string
  method: MonitorMethod
  expected_status: string
  interval_seconds: number
  timeout_seconds: number
  confirm_threshold: number
  status: MonitorStatus
  is_active: boolean
  next_check_at: string
  last_checked_at: string | null
  status_changed_at: string
  created_at: string
  updated_at: string
}

export interface MonitorCreatePayload {
  name: string
  url: string
  method?: MonitorMethod
  expected_status?: string
  interval_seconds?: number
  timeout_seconds?: number
  confirm_threshold?: number
}

export type MonitorPatchPayload = Partial<MonitorCreatePayload>
