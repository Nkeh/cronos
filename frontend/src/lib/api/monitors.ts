import { apiRequest } from './client'
import type { Monitor, MonitorCreatePayload, MonitorPatchPayload } from './types'

export function listMonitors() {
  return apiRequest<Monitor[]>('/api/v1/monitors')
}

export function getMonitor(id: string) {
  return apiRequest<Monitor>(`/api/v1/monitors/${id}`)
}

export function createMonitor(payload: MonitorCreatePayload) {
  return apiRequest<Monitor>('/api/v1/monitors', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function patchMonitor(id: string, payload: MonitorPatchPayload) {
  return apiRequest<Monitor>(`/api/v1/monitors/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteMonitor(id: string) {
  return apiRequest<void>(`/api/v1/monitors/${id}`, { method: 'DELETE' })
}

// CSRFMiddleware requires exactly Content-Type: application/json on every POST/PUT/PATCH
// (app/core/csrf.py), regardless of whether the route itself expects a body — these three
// routes take none, but still need a JSON body sent so apiRequest sets that header.

export function checkNowMonitor(id: string) {
  return apiRequest<void>(`/api/v1/monitors/${id}/check-now`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function pauseMonitor(id: string) {
  return apiRequest<Monitor>(`/api/v1/monitors/${id}/pause`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function resumeMonitor(id: string) {
  return apiRequest<Monitor>(`/api/v1/monitors/${id}/resume`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
