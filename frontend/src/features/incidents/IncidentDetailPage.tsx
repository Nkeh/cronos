import { Link, useParams } from 'react-router'
import { PageHeader } from '../../app/shell/PageHeader'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/Skeleton'
import { StatusPill } from '../../components/ui/StatusPill'
import { useToast } from '../toast/ToastProvider'
import { causeLabel } from './causeCopy'
import { CheckResultList, IncidentRail } from './Timeline'
import { useAckIncident, useIncident } from './hooks'

export function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: incident, isLoading } = useIncident(id)
  const ack = useAckIncident(id ?? '')
  const { toast } = useToast()

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!incident) {
    return (
      <div>
        <PageHeader eyebrow="What broke" title="Incident." />
        <GlassPanel className="p-6 text-center font-body text-sm text-text-muted">
          This incident doesn't exist, or isn't yours.
        </GlassPanel>
      </div>
    )
  }

  const isOpen = incident.resolved_at === null

  function handleAck() {
    ack.mutate(undefined, {
      onError: () => toast('Could not acknowledge the incident.', 'error'),
    })
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <PageHeader eyebrow="What broke" title={`${incident.subject.name ?? 'Unknown monitor'}.`} />
        <StatusPill status={isOpen ? 'down' : 'up'} label={isOpen ? 'Open' : 'Resolved'} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <IncidentRail incident={incident} />

        <div className="flex flex-col gap-6">
          <GlassPanel className="flex flex-col gap-2 p-5">
            <p className="font-body text-sm text-text">{causeLabel(incident.cause)}</p>
            {incident.last_error && (
              <p className="font-mono text-xs text-text-muted">{incident.last_error}</p>
            )}
            <div className="mt-2 flex items-center gap-4">
              <Link
                to={`/monitors/${incident.subject.id}/edit`}
                className="font-body text-xs text-accent-fg underline-offset-4 hover:underline"
              >
                View monitor
              </Link>
              {isOpen && (
                <Button
                  size="sm"
                  variant={incident.acknowledged_at ? 'ghost' : 'outline'}
                  onClick={handleAck}
                  disabled={ack.isPending || Boolean(incident.acknowledged_at)}
                >
                  {incident.acknowledged_at ? 'Acknowledged' : 'Acknowledge'}
                </Button>
              )}
            </div>
          </GlassPanel>

          <div>
            <h2 className="mb-3 font-display text-heading-3 text-text">Checks</h2>
            <CheckResultList timeline={incident.timeline} />
          </div>
        </div>
      </div>
    </div>
  )
}
