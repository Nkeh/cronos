import { Link } from 'react-router'
import { Pause, Play, Pencil, Trash2, Zap } from 'lucide-react'
import { PageHeader } from '../../app/shell/PageHeader'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { Button, buttonVariants } from '../../components/ui/Button'
import { cn } from '../../lib/cn'
import { Skeleton } from '../../components/ui/Skeleton'
import { StatusPill, statusLabels } from '../../components/ui/StatusPill'
import { UsageBar } from '../../components/ui/UsageBar'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Stagger, StaggerItem } from '../../components/motion/Stagger'
import { useAuthMe } from '../auth/hooks'
import { useToast } from '../toast/ToastProvider'
import { monitorErrorMessage, retryAfterMessage } from '../../lib/api/error-copy'
import { relativeTime, formatInterval } from '../../lib/relativeTime'
import {
  useMonitors,
  useUsage,
  useDeleteMonitor,
  useCheckNow,
  usePauseMonitor,
  useResumeMonitor,
} from './hooks'
import type { Monitor } from '../../lib/api/types'

function MonitorRow({ monitor }: { monitor: Monitor }) {
  const { toast } = useToast()
  const checkNow = useCheckNow()
  const pause = usePauseMonitor()
  const resume = useResumeMonitor()
  const del = useDeleteMonitor()

  function handleCheckNow() {
    checkNow.mutate(monitor.id, {
      onSuccess: () => toast('Check queued.', 'success'),
      onError: (error) => toast(monitorErrorMessage(error), 'error'),
    })
  }

  function handleToggle() {
    const mutation = monitor.is_active ? pause : resume
    mutation.mutate(monitor.id, {
      onError: (error) => toast(monitorErrorMessage(error), 'error'),
    })
  }

  function handleDelete() {
    del.mutate(monitor.id, {
      onError: (error) => toast(retryAfterMessage(error) ?? monitorErrorMessage(error), 'error'),
    })
  }

  return (
    <StaggerItem>
      <GlassPanel className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-3">
            <StatusPill status={monitor.status} label={statusLabels[monitor.status]} />
            <span className="font-body text-sm text-text">{monitor.name}</span>
          </div>
          <p className="font-mono text-xs text-text-muted">{monitor.url}</p>
          <div className="flex items-center gap-3 font-body text-xs text-text-muted">
            <span>{formatInterval(monitor.interval_seconds)}</span>
            <span>
              {monitor.last_checked_at
                ? `checked ${relativeTime(monitor.last_checked_at)}`
                : 'No data yet'}
            </span>
          </div>
          <div className="mt-1 h-6 w-32 rounded-sm bg-surface-raised" aria-hidden="true" />
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            aria-label={monitor.is_active ? 'Pause monitor' : 'Resume monitor'}
            onClick={handleToggle}
            disabled={pause.isPending || resume.isPending}
          >
            {monitor.is_active ? <Pause size={16} /> : <Play size={16} />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Check now"
            onClick={handleCheckNow}
            disabled={checkNow.isPending || !monitor.is_active}
          >
            <Zap size={16} />
          </Button>
          <Link
            to={`/monitors/${monitor.id}/edit`}
            aria-label="Edit monitor"
            className="inline-flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors duration-(--duration-fast) hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            <Pencil size={16} />
          </Link>
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="sm" aria-label="Delete monitor">
                <Trash2 size={16} />
              </Button>
            }
            title="Delete this monitor?"
            description={`"${monitor.name}" will stop being checked immediately. This can't be undone.`}
            confirmLabel="Delete"
            danger
            onConfirm={handleDelete}
            pending={del.isPending}
          />
        </div>
      </GlassPanel>
    </StaggerItem>
  )
}

export function MonitorsListPage() {
  const { data: me } = useAuthMe()
  const { data: monitors, isLoading } = useMonitors()
  const { data: usage } = useUsage()

  const atLimit = Boolean(usage && usage.counts.monitors >= (usage.limits.max_monitors as number))
  const unverified = me ? !me.email_verified : false
  const createDisabled = unverified || atLimit

  return (
    <div>
      <PageHeader eyebrow="Up or down" title="Monitors." />

      {usage && (
        <div className="mb-6 max-w-sm">
          <UsageBar
            used={usage.counts.monitors}
            limit={usage.limits.max_monitors as number}
            label="Monitors used"
          />
        </div>
      )}

      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {createDisabled && (
            <p className="font-body text-sm text-text-muted">
              {unverified
                ? 'Verify your email to create monitors.'
                : "You've reached your plan's monitor limit."}
            </p>
          )}
        </div>
        {createDisabled ? (
          <Button disabled>New monitor</Button>
        ) : (
          <Link to="/monitors/new" className={buttonVariants()}>
            New monitor
          </Link>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : monitors && monitors.length > 0 ? (
        <Stagger className="flex flex-col gap-3">
          {monitors.map((monitor) => (
            <MonitorRow key={monitor.id} monitor={monitor} />
          ))}
        </Stagger>
      ) : (
        <GlassPanel className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <p className="font-display text-heading-3 text-text">No monitors yet.</p>
          <p className="max-w-sm font-body text-sm text-text-muted">
            Add your first HTTP endpoint and Cronos will start checking it on its own schedule.
          </p>
          {/* The disabled case already has its explanation + disabled button above — avoid a
              second "New monitor" affordance with the same accessible name on the page. */}
          {!createDisabled && (
            <Link to="/monitors/new" className={cn(buttonVariants(), 'mt-2')}>
              New monitor
            </Link>
          )}
        </GlassPanel>
      )}
    </div>
  )
}
