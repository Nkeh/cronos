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
  open_incident_id: string | null
}

export type IncidentResolvedReason = 'recovered' | 'paused' | 'edited'

export interface IncidentSubject {
  type: 'monitor' | 'heartbeat'
  id: string
  name: string | null
}

export interface Incident {
  id: string
  subject: IncidentSubject
  cause: string
  last_error: string | null
  started_at: string
  confirmed_at: string | null
  resolved_at: string | null
  resolved_reason: IncidentResolvedReason | null
  acknowledged_at: string | null
  duration_seconds: number
}

export interface IncidentListResponse {
  items: Incident[]
  next_cursor: string | null
}

export interface CheckResultSummary {
  is_up: boolean
  status_code: number | null
  error_kind: string | null
  response_time_ms: number | null
  checked_at: string
  suppressed: boolean
}

export interface IncidentDetail extends Incident {
  timeline: CheckResultSummary[]
}

export interface OpenIncidentCount {
  count: number
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

export type ChannelKind = 'email' | 'webhook'

export interface ChannelConfig {
  address?: string
  url?: string
}

export interface Channel {
  id: string
  kind: ChannelKind
  name: string
  config: ChannelConfig
  is_default: boolean
  verified_at: string | null
  created_at: string
  updated_at: string
}

export interface ChannelCreatePayload {
  kind: ChannelKind
  name: string
  config: ChannelConfig
  is_default?: boolean
}

export type ChannelPatchPayload = Partial<Omit<ChannelCreatePayload, 'kind'>>

export interface ChannelSecretResponse {
  secret: string
}

export interface ChannelTestResponse {
  ok: boolean
  status_code: number | null
  error: string | null
}

export type DeliveryAttemptOutcome = 'sent' | 'retry' | 'failed'

export interface DeliveryAttempt {
  id: number
  attempted_at: string
  outcome: DeliveryAttemptOutcome
  status_code: number | null
  error: string | null
  duration_ms: number
}

export type DeliveryStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'suppressed'

export interface Delivery {
  id: string
  event: string
  status: DeliveryStatus
  attempts: number
  created_at: string
  sent_at: string | null
  last_error: string | null
  recent_attempts: DeliveryAttempt[]
}

export interface DeliveryListResponse {
  items: Delivery[]
  next_cursor: string | null
}

export interface MonitorChannelsResponse {
  channel_ids: string[]
}
