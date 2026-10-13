import { cn } from '../../lib/cn'

export type Status = 'up' | 'down' | 'degraded' | 'paused'

const statusClasses: Record<Status, string> = {
  up: 'border-status-up-text text-status-up-text',
  down: 'border-status-down-text text-status-down-text',
  degraded: 'border-status-degraded-text text-status-degraded-text',
  paused: 'border-status-paused-text text-status-paused-text',
}

const dotClasses: Record<Status, string> = {
  up: 'bg-status-up-dot',
  down: 'bg-status-down-dot',
  degraded: 'bg-status-degraded-dot',
  paused: 'bg-status-paused-dot',
}

export function StatusPill({ status, label }: { status: Status; label: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full border bg-transparent px-3 py-1 font-body text-xs',
        statusClasses[status],
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', dotClasses[status])} aria-hidden="true" />
      {label}
    </span>
  )
}
