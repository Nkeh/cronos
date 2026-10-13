import { forwardRef } from 'react'
import { NavLink } from 'react-router'
import type { LucideIcon } from 'lucide-react'
import { ActivePill } from './ActivePill'
import { IncidentsBadge } from './IncidentsBadge'
import { cn } from '../../../lib/cn'

interface NavItemProps {
  to: string
  label: string
  icon: LucideIcon
  badgeCount?: number
}

export const NavItem = forwardRef<HTMLAnchorElement, NavItemProps>(function NavItem(
  { to, label, icon: Icon, badgeCount },
  ref,
) {
  return (
    <NavLink
      ref={ref}
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'relative flex items-center gap-2 rounded-full px-3 py-2 font-body text-sm transition-colors duration-(--duration-fast) ease-(--ease) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring',
          isActive ? 'text-accent-fg' : 'text-text-muted hover:text-text',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && <ActivePill />}
          <span className="relative">
            <Icon size={16} />
            {badgeCount !== undefined && <IncidentsBadge count={badgeCount} />}
          </span>
          <span className={cn(isActive ? 'inline' : 'hidden sm:inline')}>{label}</span>
        </>
      )}
    </NavLink>
  )
})
