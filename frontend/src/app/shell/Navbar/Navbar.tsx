import * as Tooltip from '@radix-ui/react-tooltip'
import { useScrollDirection } from './useScrollDirection'
import { NavItem } from './NavItem'
import { AccountMenu } from './AccountMenu'
import { SearchDialog } from './SearchDialog'
import { navItems } from './nav-items'
import { cn } from '../../../lib/cn'

export function Navbar() {
  const isCompact = useScrollDirection()

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 z-40 flex w-full justify-center"
      style={{ bottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
    >
      <Tooltip.Provider delayDuration={300}>
        <div
          data-testid="navbar-capsule"
          className={cn(
            'flex w-fit max-w-[calc(100vw-2rem)] items-center gap-1 rounded-full border border-glass-border bg-glass-bg backdrop-blur-glass transition-[padding] duration-(--duration-base) ease-(--ease)',
            isCompact ? 'px-1.5 py-1.5' : 'px-2 py-2',
          )}
        >
          {navItems.map((item) => (
            <Tooltip.Root key={item.to}>
              <Tooltip.Trigger asChild>
                <NavItem
                  to={item.to}
                  label={item.label}
                  icon={item.icon}
                  badgeCount={item.to === '/incidents' ? 0 : undefined}
                />
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content
                  side="top"
                  sideOffset={8}
                  className="z-50 rounded-sm border border-border bg-surface-raised px-2 py-1 font-body text-xs text-text sm:hidden"
                >
                  {item.label}
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          ))}
          <div className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
          <SearchDialog />
          <AccountMenu />
        </div>
      </Tooltip.Provider>
    </nav>
  )
}
