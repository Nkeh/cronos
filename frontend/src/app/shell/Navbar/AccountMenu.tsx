import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { User } from 'lucide-react'
import { useNavigate } from 'react-router'
import { useTheme } from '../../../features/theme/ThemeProvider'
import { useAuthMe, useLogout } from '../../../features/auth/hooks'
import { cn } from '../../../lib/cn'

export function AccountMenu() {
  const { data } = useAuthMe()
  const { theme, setTheme } = useTheme()
  const logout = useLogout()
  const navigate = useNavigate()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          aria-label="Account menu"
          className="flex items-center gap-2 rounded-full px-3 py-2 text-text-muted transition-colors duration-(--duration-fast) hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
        >
          <User size={16} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={12}
          className="z-50 min-w-48 rounded-sm border border-border bg-surface-raised p-1 font-body text-sm shadow-glow"
        >
          {data && <div className="px-3 py-2 font-mono text-xs text-text-muted">{data.email}</div>}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          {(['system', 'light', 'dark'] as const).map((mode) => (
            <DropdownMenu.Item
              key={mode}
              onSelect={() => setTheme(mode)}
              className={cn(
                'cursor-pointer rounded-sm px-3 py-2 capitalize outline-none hover:bg-surface focus:bg-surface',
                theme === mode && 'text-accent',
              )}
            >
              {mode}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            onSelect={() => {
              logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })
            }}
            className="cursor-pointer rounded-sm px-3 py-2 text-status-down-text outline-none hover:bg-surface focus:bg-surface"
          >
            Log out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
