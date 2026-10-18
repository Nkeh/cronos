/** Plain-English labels for every `cause`/`error_kind` value the backend can produce --
 * MONITOR_CAUSES + HEARTBEAT_CAUSES in app/incidents/models.py. Kept exhaustive (not a fallback
 * guess) so a new backend cause is a visible gap here, not a silently blank label. */
const CAUSE_LABELS: Record<string, string> = {
  http_status: 'Unexpected status code',
  timeout: 'Timed out',
  connection: "Couldn't connect",
  dns: 'DNS lookup failed',
  tls: 'TLS handshake failed',
  redirects: 'Too many redirects',
  blocked: 'Blocked by security policy',
  heartbeat_missed: 'Missed check-in',
  heartbeat_fail: 'Reported failure',
}

export function causeLabel(cause: string): string {
  return CAUSE_LABELS[cause] ?? cause
}

const RESOLVED_REASON_LABELS: Record<string, string> = {
  recovered: 'Recovered',
  paused: 'Paused',
  edited: 'Edited',
}

export function resolvedReasonLabel(reason: string): string {
  return RESOLVED_REASON_LABELS[reason] ?? reason
}
