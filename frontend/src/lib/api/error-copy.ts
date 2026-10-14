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

/** Friendly copy for monitor error codes — covers every url_* code ssrf_policy.py can raise
 * (save-time validation only; connect-time enforcement is Day 7), plus the monitor-specific
 * codes monitors/router.py raises. */
const MONITOR_MESSAGES: Record<string, string> = {
  url_invalid: 'Enter a valid URL.',
  url_scheme: 'Only http:// and https:// URLs are allowed.',
  url_credentials: "URLs can't include a username or password.",
  url_port_blocked: "This URL's port isn't allowed.",
  url_host_blocked: "This host isn't allowed — it looks like a private or internal address.",
  url_resolves_private: 'This URL resolves to a private address and can’t be monitored.',
  plan_limit: "You've reached your plan's monitor limit.",
  monitor_paused: 'This monitor is paused — resume it before checking now.',
  not_found: 'That monitor no longer exists.',
  email_not_verified: 'Verify your email to create or edit monitors.',
}

export function monitorErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return MONITOR_MESSAGES[error.code] ?? error.message
  }
  return 'Something went wrong. Please try again.'
}
