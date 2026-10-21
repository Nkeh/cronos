import { apiRequest } from './client'
import type {
  Channel,
  ChannelCreatePayload,
  ChannelPatchPayload,
  ChannelSecretResponse,
  ChannelTestResponse,
  DeliveryListResponse,
  MessageResponse,
  MonitorChannelsResponse,
} from './types'

export function listChannels() {
  return apiRequest<Channel[]>('/api/v1/channels')
}

export function createChannel(payload: ChannelCreatePayload) {
  return apiRequest<Channel>('/api/v1/channels', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function patchChannel(id: string, payload: ChannelPatchPayload) {
  return apiRequest<Channel>(`/api/v1/channels/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteChannel(id: string) {
  return apiRequest<void>(`/api/v1/channels/${id}`, { method: 'DELETE' })
}

// CSRFMiddleware requires Content-Type: application/json on every POST, regardless of whether
// the route expects a body (see lib/api/monitors.ts's identical note on check-now/pause/resume).
export function verifyChannel(id: string) {
  return apiRequest<Channel>(`/api/v1/channels/${id}/verify`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function verifyChannelEmail(token: string) {
  return apiRequest<MessageResponse>('/api/v1/channels/verify-email', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export function testChannel(id: string) {
  return apiRequest<ChannelTestResponse>(`/api/v1/channels/${id}/test`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function rotateChannelSecret(id: string) {
  return apiRequest<ChannelSecretResponse>(`/api/v1/channels/${id}/rotate-secret`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function revealChannelSecret(id: string) {
  return apiRequest<ChannelSecretResponse>(`/api/v1/channels/${id}/secret`)
}

export function listChannelDeliveries(id: string, cursor?: string) {
  const qs = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return apiRequest<DeliveryListResponse>(`/api/v1/channels/${id}/deliveries${qs}`)
}

export function getMonitorChannels(monitorId: string) {
  return apiRequest<MonitorChannelsResponse>(`/api/v1/monitors/${monitorId}/channels`)
}

export function setMonitorChannels(monitorId: string, channelIds: string[]) {
  return apiRequest<MonitorChannelsResponse>(`/api/v1/monitors/${monitorId}/channels`, {
    method: 'PUT',
    body: JSON.stringify({ channel_ids: channelIds }),
  })
}
