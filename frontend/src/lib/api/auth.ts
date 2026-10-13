import { apiRequest, fetchCsrfToken } from './client'
import type { MessageResponse, UserPublic } from './types'

export { fetchCsrfToken }

export function signup(email: string, password: string) {
  return apiRequest<MessageResponse>('/api/v1/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function verifyEmail(token: string) {
  return apiRequest<MessageResponse>('/api/v1/auth/verify', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export function resendVerification() {
  return apiRequest<MessageResponse>('/api/v1/auth/verify/resend', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function login(email: string, password: string) {
  return apiRequest<UserPublic>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function logout() {
  return apiRequest<void>('/api/v1/auth/logout', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function requestPasswordReset(email: string) {
  return apiRequest<MessageResponse>('/api/v1/auth/reset-request', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function resetPassword(token: string, password: string) {
  return apiRequest<MessageResponse>('/api/v1/auth/reset', {
    method: 'POST',
    body: JSON.stringify({ token, password }),
  })
}

export function getMe() {
  return apiRequest<UserPublic>('/api/v1/auth/me')
}
