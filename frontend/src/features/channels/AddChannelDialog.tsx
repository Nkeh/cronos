import * as Dialog from '@radix-ui/react-dialog'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '../../components/ui/Button'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { cn } from '../../lib/cn'
import { ApiError } from '../../lib/api/errors'
import { channelErrorMessage } from '../../lib/api/error-copy'
import type { ChannelKind } from '../../lib/api/types'
import { useCreateChannel } from './hooks'

const selectClassName = cn(
  'h-10 w-full rounded-sm border border-border bg-surface px-3 font-body text-sm text-text',
  'transition-colors duration-(--duration-fast) ease-(--ease)',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:border-accent',
)

export function AddChannelDialog({ trigger }: { trigger: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<ChannelKind>('email')
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [url, setUrl] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const createChannel = useCreateChannel()

  function reset() {
    setKind('email')
    setName('')
    setAddress('')
    setUrl('')
    setIsDefault(false)
    createChannel.reset()
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    createChannel.mutate(
      {
        kind,
        name,
        config: kind === 'email' ? { address } : { url },
        is_default: isDefault,
      },
      {
        onSuccess: () => {
          setOpen(false)
          reset()
        },
      },
    )
  }

  const error = createChannel.error
  const fieldError = error instanceof ApiError ? error.field : undefined
  const topLevelError = error && !fieldError ? channelErrorMessage(error) : null
  const addressError = fieldError === 'config.address' ? channelErrorMessage(error) : undefined
  const urlError = fieldError === 'config.url' ? channelErrorMessage(error) : undefined

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-bg/60" />
        <Dialog.Content className="fixed left-1/2 top-24 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 rounded-sm border border-border bg-surface-raised p-5 shadow-glow">
          <Dialog.Title className="font-display text-heading-3 text-text">Add a channel.</Dialog.Title>
          <Dialog.Description className="mt-2 font-body text-sm text-text-muted">
            Monitors route to channels you choose, or to every default channel automatically.
          </Dialog.Description>

          <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4" noValidate>
            <FormField label="Kind" htmlFor="channel-kind">
              <select
                id="channel-kind"
                className={selectClassName}
                value={kind}
                onChange={(e) => setKind(e.target.value as ChannelKind)}
              >
                <option value="email">Email</option>
                <option value="webhook">Webhook</option>
              </select>
            </FormField>

            <FormField label="Name" htmlFor="channel-name">
              <Input
                id="channel-name"
                required
                maxLength={60}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </FormField>

            {kind === 'email' ? (
              <FormField label="Email address" htmlFor="channel-address" error={addressError}>
                <Input
                  id="channel-address"
                  type="email"
                  required
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  invalid={Boolean(addressError)}
                />
              </FormField>
            ) : (
              <FormField
                label="Webhook URL"
                htmlFor="channel-url"
                error={urlError}
                hint="http:// or https://, no redirects followed"
              >
                <Input
                  id="channel-url"
                  type="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  invalid={Boolean(urlError)}
                />
              </FormField>
            )}

            <label className="flex items-center gap-2 font-body text-sm text-text-muted">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="h-4 w-4 rounded-sm border border-border accent-accent-solid"
              />
              Route every new monitor here by default
            </label>

            {topLevelError && (
              <p role="alert" className="font-body text-sm text-status-down-text">
                {topLevelError}
              </p>
            )}

            <div className="mt-1 flex justify-end gap-3">
              <Dialog.Close asChild>
                <Button type="button" variant="ghost" size="sm">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button type="submit" size="sm" disabled={createChannel.isPending}>
                {createChannel.isPending ? 'Adding…' : 'Add channel'}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
