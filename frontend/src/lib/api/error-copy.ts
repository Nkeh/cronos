import { ApiError } from './errors'

/** Friendly copy for auth error codes that don't already carry a server-written message. */
const AUTH_MESSAGES: Record<string, string> = {
  invalid_credentials: 'That email or password is incorrect.',
  invalid_token: 'That link is invalid or has expired.',
  email_not_verified: 'Verify your email before continuing.',
  weak_password: 'Choose a stronger password — at least 8 characters, not a common password.',
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return AUTH_MESSAGES[error.code] ?? error.message
  }
  return 'Something went wrong. Please try again.'
}

export function retryAfterMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.code === 'rate_limited' && error.retryAfter) {
    const seconds = Math.ceil(error.retryAfter)
    return `Too many attempts — try again in ${seconds}s.`
  }
  return null
}
