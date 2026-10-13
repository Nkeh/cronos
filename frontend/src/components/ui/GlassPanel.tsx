import { type HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function GlassPanel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-sm border border-glass-border bg-glass-bg backdrop-blur-glass',
        className,
      )}
      {...props}
    />
  )
}
