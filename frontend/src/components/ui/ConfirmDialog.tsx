import * as Dialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'
import { Button } from './Button'

export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  danger,
  onConfirm,
  pending,
}: {
  trigger: ReactNode
  title: string
  description: string
  confirmLabel: string
  danger?: boolean
  onConfirm: () => void
  pending?: boolean
}) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-bg/60" />
        <Dialog.Content className="fixed left-1/2 top-24 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 rounded-sm border border-border bg-surface-raised p-5 shadow-glow">
          <Dialog.Title className="font-display text-heading-3 text-text">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 font-body text-sm text-text-muted">
            {description}
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-3">
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm">
                Cancel
              </Button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <Button
                size="sm"
                variant={danger ? 'outline' : 'solid'}
                className={danger ? 'border-status-down-text text-status-down-text hover:border-status-down-text' : undefined}
                onClick={onConfirm}
                disabled={pending}
              >
                {pending ? 'Working…' : confirmLabel}
              </Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
