import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid, ...props }, ref) => (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        'h-10 w-full rounded-sm border border-border bg-surface px-3 font-body text-sm text-text placeholder:text-text-muted',
        'transition-colors duration-(--duration-fast) ease-(--ease)',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:border-accent',
        invalid && 'border-status-down-text',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
