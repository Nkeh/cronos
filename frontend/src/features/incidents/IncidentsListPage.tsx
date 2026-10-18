import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { CheckCircle2 } from 'lucide-react'
import { PageHeader } from '../../app/shell/PageHeader'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/Skeleton'
import { Stagger, StaggerItem } from '../../components/motion/Stagger'
import { relativeTime } from '../../lib/relativeTime'
import { useToast } from '../toast/ToastProvider'
import { causeLabel, resolvedReasonLabel } from './causeCopy'
import { formatDuration } from './duration'
import { useAckIncident, useIncidents } from './hooks'
import type { Incident } from '../../lib/api/types'

/** Re-renders once a second so an open incident's duration ticks live without a refetch. */
function useTick(enabled: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!enabled) return
    const id = window.setInterval(() => setTick((t) => t + 1), 1000)
    return () => window.clearInterval(id)
  }, [enabled])
}

function IncidentRow({ incident }: { incident: Incident }) {
  const { toast } = useToast()
  const ack = useAckIncident(incident.id)
  const isOpen = incident.resolved_at === null
  useTick(isOpen)

  const durationSeconds = isOpen
    ? (Date.now() - new Date(incident.started_at).getTime()) / 1000
    : incident.duration_seconds

  function handleAck() {
    ack.mutate(undefined, {
      onError: () => toast('Could not acknowledge the incident.', 'error'),
    })
  }

  return (
    <StaggerItem>
      <GlassPanel className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-3">
            <span
              className={
                isOpen
                  ? 'h-2.5 w-2.5 animate-pulse rounded-full bg-status-down-dot motion-reduce:animate-none'
                  : 'h-2.5 w-2.5 rounded-full bg-status-up-dot'
              }
              aria-hidden="true"
            />
            <Link
              to={`/incidents/${incident.id}`}
              className="font-body text-sm text-text underline-offset-4 hover:underline"
            >
              {incident.subject.name ?? 'Unknown monitor'}
            </Link>
          </div>
          <p className="font-body text-xs text-text-muted">{causeLabel(incident.cause)}</p>
          <div className="flex items-center gap-3 font-body text-xs text-text-muted">
            <span className="font-mono tabular-nums">{formatDuration(durationSeconds)}</span>
            <span>{isOpen ? 'ongoing' : `resolved ${resolvedReasonLabel(incident.resolved_reason ?? '')}`}</span>
            <span>started {relativeTime(incident.started_at)}</span>
          </div>
        </div>

        {isOpen && (
          <Button
            variant={incident.acknowledged_at ? 'ghost' : 'outline'}
            size="sm"
            onClick={handleAck}
            disabled={ack.isPending || Boolean(incident.acknowledged_at)}
          >
            <CheckCircle2 size={16} />
            {incident.acknowledged_at ? 'Acknowledged' : 'Acknowledge'}
          </Button>
        )}
      </GlassPanel>
    </StaggerItem>
  )
}

function IncidentSection({ state, title }: { state: 'open' | 'resolved'; title: string }) {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useIncidents(state)
  const items = data?.pages.flatMap((page) => page.items) ?? []

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    )
  }

  return (
    <div>
      <h2 className="mb-3 font-display text-heading-3 text-text">{title}</h2>
      {items.length > 0 ? (
        <>
          <Stagger className="flex flex-col gap-3">
            {items.map((incident) => (
              <IncidentRow key={incident.id} incident={incident} />
            ))}
          </Stagger>
          {hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button variant="ghost" size="sm" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
                {isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      ) : (
        <GlassPanel className="flex flex-col items-center gap-2 px-6 py-10 text-center">
          <p className="font-body text-sm text-text-muted">
            {state === 'open' ? 'Nothing is down right now.' : 'No resolved incidents yet.'}
          </p>
        </GlassPanel>
      )}
    </div>
  )
}

export function IncidentsListPage() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeader eyebrow="What broke" title="Incidents." />
      <IncidentSection state="open" title="Open" />
      <IncidentSection state="resolved" title="History" />
    </div>
  )
}
