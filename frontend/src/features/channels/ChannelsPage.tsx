import { useState } from 'react'
import { Mail, Webhook, Eye, EyeOff, Copy, RefreshCw, Trash2, History, ShieldCheck } from 'lucide-react'
import { PageHeader } from '../../app/shell/PageHeader'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/Skeleton'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { Stagger, StaggerItem } from '../../components/motion/Stagger'
import { useToast } from '../toast/ToastProvider'
import { channelErrorMessage } from '../../lib/api/error-copy'
import type { Channel } from '../../lib/api/types'
import { AddChannelDialog } from './AddChannelDialog'
import { DeliveryLogDrawer } from './DeliveryLogDrawer'
import { SignatureSnippet } from './SignatureSnippet'
import {
  useChannels,
  useDeleteChannel,
  usePatchChannel,
  useRevealSecret,
  useRotateSecret,
  useTestChannel,
  useVerifyChannel,
} from './hooks'

function channelTarget(channel: Channel): string {
  return channel.kind === 'email' ? channel.config.address ?? '' : channel.config.url ?? ''
}

function ChannelRow({ channel, onShowDeliveries }: { channel: Channel; onShowDeliveries: (id: string) => void }) {
  const { toast } = useToast()
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null)

  const patchChannel = usePatchChannel(channel.id)
  const deleteChannel = useDeleteChannel()
  const verifyChannel = useVerifyChannel()
  const testChannel = useTestChannel()
  const rotateSecret = useRotateSecret(channel.id)
  const revealSecret = useRevealSecret()

  const verified = channel.verified_at !== null

  function handleVerify() {
    verifyChannel.mutate(channel.id, {
      onSuccess: (updated) => {
        toast(
          updated.verified_at
            ? 'Channel verified.'
            : channel.kind === 'email'
              ? 'Verification link sent.'
              : 'Verified.',
          'success',
        )
      },
      onError: (error) => toast(channelErrorMessage(error), 'error'),
    })
  }

  function handleTest() {
    testChannel.mutate(channel.id, {
      onSuccess: (result) => toast(result.ok ? 'Test sent.' : result.error ?? 'Test failed.', result.ok ? 'success' : 'error'),
      onError: (error) => toast(channelErrorMessage(error), 'error'),
    })
  }

  function handleToggleDefault() {
    patchChannel.mutate(
      { is_default: !channel.is_default },
      { onError: (error) => toast(channelErrorMessage(error), 'error') },
    )
  }

  function handleReveal() {
    if (revealedSecret) {
      setRevealedSecret(null)
      return
    }
    revealSecret.mutate(channel.id, {
      onSuccess: (result) => setRevealedSecret(result.secret),
      onError: (error) => toast(channelErrorMessage(error), 'error'),
    })
  }

  function handleCopy() {
    if (!revealedSecret) return
    navigator.clipboard.writeText(revealedSecret).then(() => toast('Secret copied.', 'success'))
  }

  function handleRotate() {
    rotateSecret.mutate(undefined, {
      onSuccess: (result) => {
        setRevealedSecret(result.secret)
        toast('Secret rotated.', 'success')
      },
      onError: (error) => toast(channelErrorMessage(error), 'error'),
    })
  }

  function handleDelete() {
    deleteChannel.mutate(channel.id, {
      onError: (error) => toast(channelErrorMessage(error), 'error'),
    })
  }

  return (
    <StaggerItem>
      <GlassPanel className="flex flex-col gap-3 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            {channel.kind === 'email' ? (
              <Mail size={16} className="text-text-muted" aria-hidden="true" />
            ) : (
              <Webhook size={16} className="text-text-muted" aria-hidden="true" />
            )}
            <div className="flex flex-col gap-0.5">
              <span className="font-body text-sm text-text">{channel.name}</span>
              <span className="font-mono text-xs text-text-muted">{channelTarget(channel)}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-body text-xs ${
                verified
                  ? 'border-status-up-text text-status-up-text'
                  : 'border-status-degraded-text text-status-degraded-text'
              }`}
            >
              <ShieldCheck size={12} aria-hidden="true" />
              {verified ? 'Verified' : 'Unverified'}
            </span>
            <label className="flex items-center gap-1.5 font-body text-xs text-text-muted">
              <input
                type="checkbox"
                checked={channel.is_default}
                onChange={handleToggleDefault}
                disabled={patchChannel.isPending}
                className="h-4 w-4 rounded-sm border border-border accent-accent-solid"
              />
              Default
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {!verified && (
            <Button variant="outline" size="sm" onClick={handleVerify} disabled={verifyChannel.isPending}>
              {verifyChannel.isPending ? 'Verifying…' : 'Verify'}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={handleTest} disabled={!verified || testChannel.isPending}>
            Send test
          </Button>
          {channel.kind === 'webhook' && (
            <>
              <Button variant="ghost" size="sm" onClick={handleReveal} disabled={revealSecret.isPending}>
                {revealedSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                {revealedSecret ? 'Hide secret' : 'Reveal secret'}
              </Button>
              {revealedSecret && (
                <Button variant="ghost" size="sm" onClick={handleCopy}>
                  <Copy size={14} />
                  Copy
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={handleRotate} disabled={rotateSecret.isPending}>
                <RefreshCw size={14} />
                Rotate
              </Button>
            </>
          )}
          <Button variant="ghost" size="sm" onClick={() => onShowDeliveries(channel.id)}>
            <History size={14} />
            Deliveries
          </Button>
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="sm" aria-label="Delete channel">
                <Trash2 size={14} />
              </Button>
            }
            title="Delete this channel?"
            description={`"${channel.name}" will stop receiving alerts immediately. This can't be undone.`}
            confirmLabel="Delete"
            danger
            onConfirm={handleDelete}
            pending={deleteChannel.isPending}
          />
        </div>

        {revealedSecret && (
          <p className="rounded-sm border border-border bg-surface px-3 py-2 font-mono text-xs text-text">
            {revealedSecret}
          </p>
        )}
      </GlassPanel>
    </StaggerItem>
  )
}

export function ChannelsPage() {
  const { data: channels, isLoading } = useChannels()
  const [deliveriesFor, setDeliveriesFor] = useState<string | null>(null)

  return (
    <div>
      <PageHeader eyebrow="Where alerts go" title="Notification channels." />

      <div className="mb-6 flex justify-end">
        <AddChannelDialog trigger={<Button>Add channel</Button>} />
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : channels && channels.length > 0 ? (
        <Stagger className="flex flex-col gap-3">
          {channels.map((channel) => (
            <ChannelRow key={channel.id} channel={channel} onShowDeliveries={setDeliveriesFor} />
          ))}
        </Stagger>
      ) : (
        <GlassPanel className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <p className="font-display text-heading-3 text-text">No channels yet.</p>
          <p className="max-w-sm font-body text-sm text-text-muted">
            Add an email or webhook channel so Cronos has somewhere to send alerts.
          </p>
        </GlassPanel>
      )}

      <div className="mt-10 flex flex-col gap-3">
        <h2 className="font-display text-heading-3 text-text">Verifying webhook signatures.</h2>
        <p className="max-w-2xl font-body text-sm text-text-muted">
          Every webhook delivery is signed with HMAC-SHA256 over the request timestamp and raw
          body. Reject anything older than 5 minutes.
        </p>
        <SignatureSnippet />
      </div>

      <DeliveryLogDrawer
        channelId={deliveriesFor ?? undefined}
        open={deliveriesFor !== null}
        onOpenChange={(open) => !open && setDeliveriesFor(null)}
      />
    </div>
  )
}
