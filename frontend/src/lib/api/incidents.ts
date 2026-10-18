import { apiRequest } from './client'
import type { Incident, IncidentDetail, IncidentListResponse, OpenIncidentCount } from './types'

export interface ListIncidentsParams {
  state?: 'open' | 'resolved'
  monitor_id?: string
  cursor?: string
  limit?: number
}

function buildQuery(params: ListIncidentsParams): string {
  const search = new URLSearchParams()
  if (params.state) search.set('state', params.state)
  if (params.monitor_id) search.set('monitor_id', params.monitor_id)
  if (params.cursor) search.set('cursor', params.cursor)
  if (params.limit) search.set('limit', String(params.limit))
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export function listIncidents(params: ListIncidentsParams = {}) {
  return apiRequest<IncidentListResponse>(`/api/v1/incidents${buildQuery(params)}`)
}

export function getIncident(id: string) {
  return apiRequest<IncidentDetail>(`/api/v1/incidents/${id}`)
}

// CSRFMiddleware requires Content-Type: application/json on every POST, regardless of whether
// the route expects a body (see lib/api/monitors.ts's identical note on check-now/pause/resume).
export function ackIncident(id: string) {
  return apiRequest<Incident>(`/api/v1/incidents/${id}/ack`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function getOpenIncidentCount() {
  return apiRequest<OpenIncidentCount>('/api/v1/incidents/open-count')
}
