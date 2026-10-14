import { PageHeader } from '../../app/shell/PageHeader'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { Skeleton } from '../../components/ui/Skeleton'
import { statusLabels, type Status } from '../../components/ui/StatusPill'
import { NumberTicker } from '../../components/motion/NumberTicker'
import { Stagger, StaggerItem } from '../../components/motion/Stagger'
import { useMonitors } from '../../features/monitors/hooks'

const STATUS_ORDER: Status[] = ['up', 'down', 'paused', 'new']

const textClassByStatus: Record<Status, string> = {
  new: 'text-status-new-text',
  up: 'text-status-up-text',
  down: 'text-status-down-text',
  degraded: 'text-status-degraded-text',
  paused: 'text-status-paused-text',
}

export function OverviewPage() {
  const { data: monitors, isLoading } = useMonitors()

  const counts: Record<Status, number> = { new: 0, up: 0, down: 0, degraded: 0, paused: 0 }
  for (const monitor of monitors ?? []) {
    counts[monitor.status] += 1
  }

  return (
    <div>
      <PageHeader eyebrow="Live checks" title="Overview." />

      {isLoading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <Stagger className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STATUS_ORDER.map((status) => (
            <StaggerItem key={status}>
              <GlassPanel className="flex flex-col gap-2 p-5">
                <span className="font-body text-sm text-text-muted">{statusLabels[status]}</span>
                <NumberTicker
                  value={counts[status]}
                  className={`font-mono text-display-2 ${textClassByStatus[status]}`}
                />
              </GlassPanel>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  )
}
