import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'

/** Placeholder with a ⌘K hint — the real command palette arrives Day 12. */
export function SearchDialog() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          aria-label="Search"
          className="flex items-center gap-2 rounded-full px-3 py-2 text-text-muted transition-colors duration-(--duration-fast) hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
        >
          <Search size={16} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-bg/60" />
        <Dialog.Content className="fixed left-1/2 top-24 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 rounded-sm border border-border bg-surface-raised p-5 shadow-glow">
          <Dialog.Title className="font-display text-heading-3 text-text">Search</Dialog.Title>
          <Dialog.Description className="mt-2 font-body text-sm text-text-muted">
            The full command palette (⌘K navigation and actions) arrives on Day 12. Press{' '}
            <kbd className="rounded-sm border border-border px-1 font-mono text-xs">Esc</kbd> to
            close.
          </Dialog.Description>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
