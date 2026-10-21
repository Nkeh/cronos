import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ChevronDown } from 'lucide-react'
import { PageHeader } from '../../app/shell/PageHeader'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/Skeleton'
import { cn } from '../../lib/cn'
import { useAuthMe } from '../auth/hooks'
import { ApiError } from '../../lib/api/errors'
import { monitorErrorMessage } from '../../lib/api/error-copy'
import { useCreateMonitor, useMonitor, usePatchMonitor, useUsage } from './hooks'
import { useChannels, useMonitorChannels } from '../channels/hooks'
import { setMonitorChannels } from '../../lib/api/channels'
import type { MonitorMethod } from '../../lib/api/types'

const selectClassName = cn(
  'h-10 w-full rounded-sm border border-border bg-surface px-3 font-body text-sm text-text',
  'transition-colors duration-(--duration-fast) ease-(--ease)',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:border-accent',
)

export function MonitorFormPage() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const { data: me } = useAuthMe()
  const { data: usage } = useUsage()
  const { data: existing, isLoading: isLoadingExisting } = useMonitor(id)
  const { data: channels } = useChannels()
  const { data: routedChannels } = useMonitorChannels(id)

  const createMonitor = useCreateMonitor()
  const patchMonitor = usePatchMonitor(id ?? '')
  const mutation = isEdit ? patchMonitor : createMonitor

  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [method, setMethod] = useState<MonitorMethod>('GET')
  const [expectedStatus, setExpectedStatus] = useState('2xx')
  const [intervalSeconds, setIntervalSeconds] = useState(300)
  const [timeoutSeconds, setTimeoutSeconds] = useState(10)
  const [confirmThreshold, setConfirmThreshold] = useState(2)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [channelIds, setChannelIds] = useState<string[]>([])
  const [channelIdsTouched, setChannelIdsTouched] = useState(false)

  useEffect(() => {
    if (!existing) return
    setName(existing.name)
    setUrl(existing.url)
    setMethod(existing.method)
    setExpectedStatus(existing.expected_status)
    setIntervalSeconds(existing.interval_seconds)
    setTimeoutSeconds(existing.timeout_seconds)
    setConfirmThreshold(existing.confirm_threshold)
  }, [existing])

  // Edit path: once routing loads, show what's actually routed. Create path: pre-select every
  // default channel client-side -- the real pre-selection already happened server-side (the
  // account-verify/monitor-create hooks), this just keeps the displayed state honest, and lets
  // the user adjust it before the first save.
  useEffect(() => {
    if (channelIdsTouched) return
    if (isEdit) {
      if (routedChannels) setChannelIds(routedChannels.channel_ids)
    } else if (channels) {
      setChannelIds(channels.filter((c) => c.is_default).map((c) => c.id))
    }
  }, [isEdit, channels, routedChannels, channelIdsTouched])

  function toggleChannel(channelId: string) {
    setChannelIdsTouched(true)
    setChannelIds((prev) =>
      prev.includes(channelId) ? prev.filter((id) => id !== channelId) : [...prev, channelId],
    )
  }

  const unverified = me ? !me.email_verified : false
  const atLimit = Boolean(
    usage && !isEdit && usage.counts.monitors >= (usage.limits.max_monitors as number),
  )
  const submitDisabled = unverified || atLimit || mutation.isPending

  const error = mutation.error
  const fieldError = error instanceof ApiError ? error.field : undefined
  const topLevelError = error && !fieldError ? monitorErrorMessage(error) : null
  const urlError = fieldError === 'url' ? monitorErrorMessage(error) : undefined
  const timeoutError = fieldError === 'timeout_seconds' ? monitorErrorMessage(error) : undefined

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const payload = {
      name,
      url,
      method,
      expected_status: expectedStatus,
      interval_seconds: intervalSeconds,
      timeout_seconds: timeoutSeconds,
      confirm_threshold: confirmThreshold,
    }
    mutation.mutate(payload, {
      onSuccess: async (monitor) => {
        // Untouched means "leave whatever routing the server already applied" -- for a new
        // monitor that's the default-channel hook; for an edit, there's nothing to change.
        if (channelIdsTouched) {
          await setMonitorChannels(monitor.id, channelIds).catch(() => undefined)
        }
        navigate('/monitors')
      },
    })
  }

  if (isEdit && isLoadingExisting) {
    return (
      <div>
        <PageHeader eyebrow="Up or down" title="Monitors." />
        <Skeleton className="h-64 w-full max-w-lg" />
      </div>
    )
  }

  return (
    <div>
      <PageHeader eyebrow="Up or down" title={isEdit ? 'Edit monitor.' : 'New monitor.'} />

      {unverified && (
        <p className="mb-4 font-body text-sm text-status-degraded-text" role="alert">
          Verify your email to {isEdit ? 'edit' : 'create'} monitors.
        </p>
      )}
      {atLimit && (
        <p className="mb-4 font-body text-sm text-status-degraded-text" role="alert">
          You've reached your plan's monitor limit.
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex max-w-lg flex-col gap-4" noValidate>
        <FormField label="Name" htmlFor="name">
          <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>

        <FormField label="URL" htmlFor="url" error={urlError} hint="http:// or https://, GET/HEAD only">
          <Input
            id="url"
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            invalid={Boolean(urlError)}
          />
        </FormField>

        <FormField label="Method" htmlFor="method">
          <select
            id="method"
            className={selectClassName}
            value={method}
            onChange={(e) => setMethod(e.target.value as MonitorMethod)}
          >
            <option value="GET">GET</option>
            <option value="HEAD">HEAD</option>
          </select>
        </FormField>

        <FormField
          label="Expected status"
          htmlFor="expected_status"
          hint="2xx, or an exact code like 204"
        >
          <Input
            id="expected_status"
            required
            value={expectedStatus}
            onChange={(e) => setExpectedStatus(e.target.value)}
          />
        </FormField>

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          aria-expanded={showAdvanced}
          className="flex items-center gap-1.5 self-start font-body text-sm text-text-muted transition-colors duration-(--duration-fast) hover:text-text"
        >
          <ChevronDown
            size={14}
            className={cn('transition-transform duration-(--duration-fast)', showAdvanced && 'rotate-180')}
          />
          Advanced
        </button>

        {showAdvanced && (
          <div className="flex flex-col gap-4 border-l border-border pl-4">
            <FormField
              label="Interval (seconds)"
              htmlFor="interval_seconds"
              hint="How often Cronos checks this monitor"
            >
              <Input
                id="interval_seconds"
                type="number"
                min={30}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              />
            </FormField>
            <FormField
              label="Timeout (seconds)"
              htmlFor="timeout_seconds"
              error={timeoutError}
              hint="Must be less than the interval"
            >
              <Input
                id="timeout_seconds"
                type="number"
                min={1}
                max={60}
                value={timeoutSeconds}
                onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                invalid={Boolean(timeoutError)}
              />
            </FormField>
            <FormField
              label="Confirm threshold"
              htmlFor="confirm_threshold"
              hint="Consecutive failures before an incident opens"
            >
              <Input
                id="confirm_threshold"
                type="number"
                min={1}
                max={10}
                value={confirmThreshold}
                onChange={(e) => setConfirmThreshold(Number(e.target.value))}
              />
            </FormField>
          </div>
        )}

        <FormField label="Alert channels" htmlFor="channel-ids">
          {channels && channels.length > 0 ? (
            <div id="channel-ids" className="flex flex-col gap-2 rounded-sm border border-border p-3">
              {channels.map((channel) => (
                <label key={channel.id} className="flex items-center gap-2 font-body text-sm text-text">
                  <input
                    type="checkbox"
                    checked={channelIds.includes(channel.id)}
                    onChange={() => toggleChannel(channel.id)}
                    className="h-4 w-4 rounded-sm border border-border accent-accent-solid"
                  />
                  {channel.name}
                  {channel.is_default && (
                    <span className="font-body text-xs text-text-muted">(default)</span>
                  )}
                </label>
              ))}
            </div>
          ) : (
            <p className="font-body text-sm text-text-muted">
              No channels yet — add one under Account → Notification channels.
            </p>
          )}
        </FormField>

        {topLevelError && (
          <p role="alert" className="font-body text-sm text-status-down-text">
            {topLevelError}
          </p>
        )}

        <Button type="submit" disabled={submitDisabled}>
          {mutation.isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create monitor'}
        </Button>
      </form>
    </div>
  )
}
