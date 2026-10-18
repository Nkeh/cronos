import { describe, expect, it } from 'vitest'
import { causeLabel, resolvedReasonLabel } from './causeCopy'

describe('causeLabel', () => {
  const monitorCauses = ['http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked']
  const heartbeatCauses = ['heartbeat_missed', 'heartbeat_fail']

  it.each([...monitorCauses, ...heartbeatCauses])(
    'has a plain-English label for every backend cause (%s)',
    (cause) => {
      expect(causeLabel(cause)).not.toBe(cause)
    },
  )

  it('falls back to the raw value for an unknown cause rather than throwing', () => {
    expect(causeLabel('made_up')).toBe('made_up')
  })
})

describe('resolvedReasonLabel', () => {
  it.each(['recovered', 'paused', 'edited'])('labels every backend resolved_reason (%s)', (reason) => {
    expect(resolvedReasonLabel(reason)).not.toBe(reason)
  })
})
