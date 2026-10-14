const UNITS: [unit: Intl.RelativeTimeFormatUnit, seconds: number][] = [
  ['year', 31536000],
  ['month', 2592000],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "3 minutes ago", "just now" — used for last-checked timestamps. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const deltaSeconds = (new Date(iso).getTime() - now.getTime()) / 1000
  const absSeconds = Math.abs(deltaSeconds)

  if (absSeconds < 10) return 'just now'

  for (const [unit, unitSeconds] of UNITS) {
    if (absSeconds >= unitSeconds || unit === 'second') {
      const value = Math.round(deltaSeconds / unitSeconds)
      return formatter.format(value, unit)
    }
  }
  return 'just now'
}

/** "every 5m", "every 2h 30m" — used for a monitor's check interval. */
export function formatInterval(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  if (hours > 0) {
    return minutes > 0 ? `every ${hours}h ${minutes}m` : `every ${hours}h`
  }
  if (minutes > 0) return `every ${minutes}m`
  return `every ${seconds}s`
}
