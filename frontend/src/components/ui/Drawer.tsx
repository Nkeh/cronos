import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { duration, ease } from '../motion/tokens'

/** A Radix Dialog anchored full-height to the right edge, sliding in via `transform` (motion/
 * react already respects the app-wide `MotionConfig reducedMotion="user"` setting -- see
 * app/App.tsx). Controlled (no uncontrolled trigger like ConfirmDialog): the caller owns `open`
 * so AnimatePresence can mount/unmount it itself for the exit animation. */
export function Drawer({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50 bg-bg/60"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration.fast, ease }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount>
              <motion.div
                className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-surface-raised shadow-glow"
                initial={{ x: '100%' }}
                animate={{ x: 0 }}
                exit={{ x: '100%' }}
                transition={{ duration: duration.base, ease }}
              >
                <div className="flex items-center justify-between border-b border-border px-5 py-4">
                  <Dialog.Title className="font-display text-heading-3 text-text">{title}</Dialog.Title>
                  <Dialog.Close asChild>
                    <button
                      aria-label="Close"
                      className="rounded-sm p-1 text-text-muted transition-colors duration-(--duration-fast) hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                    >
                      <X size={18} />
                    </button>
                  </Dialog.Close>
                </div>
                <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
