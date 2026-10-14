import { cn } from '../../lib/cn'

export function UsageBar({ used, limit, label }: { used: number; limit: number; label: string }) {
  const ratio = limit > 0 ? Math.min(used / limit, 1) : 0
  const atLimit = used >= limit
  const nearLimit = !atLimit && ratio >= 0.8

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between font-body text-sm text-text-muted">
        <span>{label}</span>
        <span className="font-mono text-text" data-numeric>
          {used} / {limit}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-(--duration-base) ease-(--ease)',
            atLimit
              ? 'bg-status-down-text'
              : nearLimit
                ? 'bg-status-degraded-text'
                : 'bg-accent',
          )}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  )
}
