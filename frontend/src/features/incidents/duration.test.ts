import { describe, expect, it } from 'vitest'
import { formatDuration } from './duration'

describe('formatDuration', () => {
  it('renders seconds only under a minute', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('renders minutes and seconds under an hour', () => {
    expect(formatDuration(200)).toBe('3m 20s')
  })

  it('renders hours and minutes, dropping seconds, at an hour or more', () => {
    expect(formatDuration(7500)).toBe('2h 5m')
  })

  it('floors fractional seconds and never goes negative', () => {
    expect(formatDuration(5.9)).toBe('5s')
    expect(formatDuration(-10)).toBe('0s')
  })
})
