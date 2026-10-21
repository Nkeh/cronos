import { Drawer } from '../../components/ui/Drawer'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/Skeleton'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { relativeTime } from '../../lib/relativeTime'
import { useChannelDeliveries } from './hooks'
import type { Delivery, DeliveryAttemptOutcome, DeliveryStatus } from '../../lib/api/types'

const STATUS_CLASSES: Record<DeliveryStatus, string> = {
  pending: 'border-status-new-text text-status-new-text',
  sending: 'border-status-new-text text-status-new-text',
  sent: 'border-status-up-text text-status-up-text',
  failed: 'border-status-down-text text-status-down-text',
  suppressed: 'border-status-paused-text text-status-paused-text',
}

const OUTCOME_CLASSES: Record<DeliveryAttemptOutcome, string> = {
  sent: 'text-status-up-text',
  retry: 'text-status-degraded-text',
  failed: 'text-status-down-text',
}

function DeliveryRow({ delivery }: { delivery: Delivery }) {
  return (
    <GlassPanel className="flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-body text-xs ${STATUS_CLASSES[delivery.status]}`}
        >
          {delivery.status}
        </span>
        <span className="font-body text-xs text-text-muted">{relativeTime(delivery.created_at)}</span>
      </div>
      <p className="font-body text-sm text-text">{delivery.event}</p>
      {delivery.last_error && (
        <p className="font-mono text-xs text-status-down-text">{delivery.last_error}</p>
      )}
      {delivery.recent_attempts.length > 0 && (
        <ul className="mt-1 flex flex-col gap-1 border-t border-border pt-2">
          {delivery.recent_attempts.map((attempt) => (
            <li key={attempt.id} className="flex items-center justify-between font-mono text-xs">
              <span className={OUTCOME_CLASSES[attempt.outcome]}>
                {attempt.outcome}
                {attempt.status_code ? ` (${attempt.status_code})` : ''}
              </span>
              <span className="text-text-muted">{relativeTime(attempt.attempted_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  )
}

export function DeliveryLogDrawer({
  channelId,
  open,
  onOpenChange,
}: {
  channelId: string | undefined
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useChannelDeliveries(open ? channelId : undefined)
  const items = data?.pages.flatMap((page) => page.items) ?? []

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="Delivery log.">
      {isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : items.length > 0 ? (
        <div className="flex flex-col gap-3">
          {items.map((delivery) => (
            <DeliveryRow key={delivery.id} delivery={delivery} />
          ))}
          {hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <p className="font-body text-sm text-text-muted">No deliveries yet.</p>
      )}
    </Drawer>
  )
}
